import pandas as pd
import numpy as np

import sandy
from sandy.core.endf6 import _FormattedFile

import logging
import functools

__author__ = "Jan Malec"
__all__ = [
        "Pendf",
        ]

__version__ = "0.1.0"

pd.options.display.float_format = '{:.5e}'.format


class Pendf(_FormattedFile):
    """
    Container for pendf information grouped by MAT, MF and MT numbers.
    """
    def _from_text(self, text):
        """Reads a pendf file from a text string.
        
        Parameters
        ----------
        text : `str`
            Text string to be parsed.
        
        Returns
        -------
        `sandy.Pendf`
            Pendf object.
        """
        self._text = text
        self._read_text()
        return self

    def read_temps(self, mat):
        """
        Read TEMPs from a pendf file.
        
        Parameters
        ----------
        tape : `sandy.formats.endf6.Endf6`
            ENDF-6 file
        mat : `int`
            MAT number of the material to be read
        
        Returns
        -------
        `pandas.DataFrame`
            TEMPs section of the pendf file
        """
        # Get the number of lines in the section
        no_lines = int(self._get_section_df(mat, 1, 451)["N2"][3]) + 5
        # Get the length of the dataframe
        df_len = len(self._get_section_df(mat, 1, 451))
        # Calculate the number of temperatures
        no_temps = int(df_len/no_lines)
        # Get the temperature lines
        temp_lines = [i * no_lines + 3 for i in range(no_temps)]
        # Get the temperatures from the dataframe
        temps = [self._get_section_df(9228, 1, 451)["C1"][i] for i in temp_lines]
        # Convert the temperatures to floats
        temps = list(map(float, temps))
        return temps

    def gen_mf3_dic(self, mat):
        temps = self.read_temps(mat)
        """Generate a dictionary with the MF3 data from a tape"""
        xs_lengths = dict()
        no_points = int(self._get_section_df(mat, 3, 1)["N2"][1])
        no_lines = int(np.ceil(no_points*2/6))
        xs_lengths[temps[0]] = no_lines
        for t in temps[1:]:
            # for all temperatures exept last, get the next n3_points
            no_points = int(self._get_section_df(mat, 3, 1).iloc[no_lines+4]["N2"])
            no_lines += int(np.ceil(no_points*2/6+3))
            xs_lengths[t] = no_lines
        return xs_lengths

    def get_mf3_temp(self, mat, mt, temp):
        mf=3
        xs_lengths = self.gen_mf3_dic(mat)
        dict_temps = sorted(list(xs_lengths.keys()))
        if temp not in xs_lengths.keys():
            raise ValueError("Temperature not in tape")
        else:
            if temp == dict_temps[0]:
                df = self._get_section_df(mat, mf, mt).iloc[:xs_lengths[temp]+3]
            else:
                temp_prev = dict_temps[dict_temps.index(temp)-1]
                df = self._get_section_df(mat, mf, mt).iloc[xs_lengths[temp_prev]+3:xs_lengths[temp]+3]
        return df
    
    def get_mf3_sect(self, mat, mt, temp):
        mf = 3
        df = self.get_mf3_temp(mat, mt, temp)
        out = {
                "MAT": mat,
                "MF": mf,
                "MT": mt,
                }
        i = 0
        C, i = sandy.read_cont(df, i)
        add = {
                "ZA": C.C1,
                "AWR": C.C2,
                "PFLAG": C.L2,
                }
        out.update(add)
        T, i = sandy.read_tab1(df, i)
        add = {
                "QM": T.C1,
                "QI": T.C2,
                "LR": T.L2,
                "NBT": T.NBT,
                "INT": T.INT,
                "E": T.x,
                "XS": T.y,
                }
        out.update(add)
        return out  
    
def get_xs_temp(tape, temp):
    data = []
    # read cross sections
    #tape = tape.filter_by(listmf=[3])
    keep = "first"
    for mat, mf, mt in tape.data:
        if mf != 3:
            continue
        sec = tape.get_mf3_sect(mat, mt, temp)
        if sec['INT'] != [2]:
            logging.warning(f"skip MAT{mat}/MF{mf}/MT{mt} "
                            "because interpolation schme is not lin-lin")
            continue
        xs = pd.Series(sec["XS"], index=sec["E"], name=(mat, mt)) \
                .rename_axis("E") \
                .to_frame()
        mask_duplicates = xs.index.duplicated(keep=keep)
        for energy in xs.index[mask_duplicates]:
            logging.warning("found duplicate energy for "
                            f"MAT{mat}/MF{mf}/MT{mt} "
                            f"at {energy:.5e} MeV, keep only {keep} value")
        xs = xs[~mask_duplicates]
        data.append(xs)
    # read nubar
    tape = tape.filter_by(listmf=[1], listmt=[452, 455, 456])
    keep = "first"
    for mat, mf, mt in tape.data:
        sec = tape.read_section(mat, mf, mt)
        if sec["LNU"] != 2:
            logging.warning(f"skip MAT{mat}/MF{mf}/MT{mt} "
                            "because not tabulated")
            continue
        if sec['INT'] != [2]:
            logging.warning(f"skip MAT{mat}/MF{mf}/MT{mt} "
                            "because interpolation schme is not lin-lin")
            continue
        xs = pd.Series(sec["NU"], index=sec["E"], name=(mat, mt)) \
                .rename_axis("E") \
                .to_frame()
        mask_duplicates = xs.index.duplicated(keep=keep)
        for energy in xs.index[mask_duplicates]:
            logging.warning("found duplicate energy for "
                            f"MAT{mat}/MF{mf}/MT{mt} "
                            f"at {energy:.5e} MeV, keep only {keep} value")
        xs = xs[~mask_duplicates]
        data.append(xs)
    if not data:
        raise sandy.Error("cross sections were not found")
    # should we sort index?

    def foo(l, r):
        how = "outer"
        return pd.merge(l, r, left_index=True, right_index=True, how=how)

    df = functools.reduce(foo, data) \
                    .interpolate(method='slinear', axis=0) \
                    .fillna(0)
    return df