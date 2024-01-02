import pandas as pd
import numpy as np

import sandy
from sandy.core.endf6 import _FormattedFile

import logging
import functools
from tempfile import TemporaryDirectory
from os.path import join

__author__ = "Jan Malec"
__all__ = [
        "Pendf",
        ]

__version__ = "0.1.0"

pd.options.display.float_format = '{:.5e}'.format

def _split_pendf_format_1(lines):
    """
    Splits the given lines into sections based on a specific line pattern.

    Args:
        lines (list): The list of lines to be split.

    Returns:
        dict: A dictionary where the keys are the section indexes (starting from 1) and the values are the corresponding sections.
    """
    line_to_count = "                                                                     0 0  0    0"
    indexes = [i for i, line in enumerate(lines) if line == line_to_count]
    # each section ends at one of the indexes. Split by indexes
    sections = []
    for i, index in enumerate(indexes):
        if i == 0:
            sections.append(lines[:index])
        else:
            sections.append(lines[indexes[i-1]:index])
    # add the last line from lines to all sections
    for section in sections:
        section.append(lines[indexes[-1]+1])
        section.append('\n')
    # Convert all sections back to text
    sections = [''.join(section) for section in sections]
    # convert to dict with indexes from 1
    return {i+1: section for i, section in enumerate(sections)}

def _split_pendf_format_2(lines):
    """
    Splits the given lines of a pendf file into temperature sections based on the (mat, mf, mt) values.

    Args:
        lines (list): The lines of the pendf file.

    Returns:
        dict: A dictionary containing temperature sections as values, where the keys are the temperature section IDs.
    """
    current_temp_id = 1
    last_index = 0
    last_mat_mf_mt = None
    temperature_sections = dict()
    for line in text:
        # Skip empty lines
        if line.strip() == '':
            continue

        # Extract mat, mf, mt, and index values
        try:
            mat, mf, mt, index = int(line[66:70].strip()), int(line[70:72].strip()), int(line[72:75].strip()), int(line[75:80].strip())
        except ValueError:
            print("Could not read index for:", line)
            continue
        # Check for a change in (mat, mf, mt)
        if (mat, mf, mt) != last_mat_mf_mt and mf != 0 and mt != 0:
            current_temp_id = 1
            last_mat_mf_mt = (mat, mf, mt)
            #print("new section", mat, mf, mt, index)
        elif index == 1 and last_index != 1 and mf != 0 and mt != 0 and last_index != 99999:
            # New temperature section for the same (mat, mf, mt)
            current_temp_id += 1

        # Initialize the temperature section if not already done
        if current_temp_id not in temperature_sections:
            temperature_sections[current_temp_id] = []

        # Append the line to the current temperature section
        if mf != 0 and mt != 0:
            temperature_sections[current_temp_id].append(line)
        # otherwise append to all temperature sections
        else:
            for temp_id in temperature_sections:
                temperature_sections[temp_id].append(line)
        last_index = index

    # Convert lists of lines to strings
    for temp_id in temperature_sections:
        temperature_sections[temp_id] = ''.join(temperature_sections[temp_id])

    return temperature_sections


def split_pendf_by_temperature(text):
    """
    Splits a PENDF file into sections based on temperature.

    Args:
        text (str): The content of the PENDF file.

    Returns:
        dict: A dictionary where the keys are temperature section IDs and the values are the corresponding sections as strings.
    """


    # If not split, split the text in lines
    if isinstance(text, str):
        text = text.split('\n')
    
    # Count the number of EOF lines to determine format
    # Sometimes entire files is repeated, sometimes each section
    eof_line  = "                                                                     0 0  0    0"
    eof_lines = text.count(eof_line)

    # if more than on EOF, the entire file is repeated
    if eof_lines > 1:
        print("Entire file is repeated.")
        # Split by the first line
        return _split_pendf_format_1(text)
    # otherwise each section is repeated
    elif eof_lines == 1:
        print("Each section is repeated.")
        # Split by temperature
        return _split_pendf_format_2(text)
    else:
        print("No EOF lines found.")
        return None

def get_pendf_endf(text):
    """
    Returns a sandy.endf6 object from pendf files with
    multiple temperatures.

    Parameters:
    text (str): The content of the PENDF file.

    Returns:
    dict: A dictionary containing sandy.endf6 objects for each temperature section.
    """
    temperature_sections = split_pendf_by_temperature(text)
    pendf_sections = {temp_id: sandy.Endf6.from_text(section) for temp_id, section in temperature_sections.items()}
    return pendf_sections

def combine_pendf_sections(temperature_sections):
    """
    Combines multiple PENDF sections into a single section and writes it to an output file.

    Parameters:
    - temperature_sections (dict): A dictionary containing the PENDF sections for different temperatures.
                                  The keys are the temperature IDs and the values are the corresponding sections.
    - output_file_path (str): The file path where the combined PENDF section will be written.

    Returns:
    - merged_section (str): The combined PENDF section.
    """
    def extract_mat_mf_mt(line):
        return int(line[66:70].strip()), int(line[70:72].strip()), int(line[72:75].strip())

    def is_zero_line(line):
        mat, mf, mt = extract_mat_mf_mt(line)
        return mf == 0 or mt == 0

    # Preprocess: Split each section into lines
    preprocessed_sections = {temp_id: section.split('\n') for temp_id, section in temperature_sections.items()}
    print(preprocessed_sections.keys())

    first_id = next(iter(preprocessed_sections))
    combined_lines = [preprocessed_sections[first_id][0]]
    current_mat_mf_mt = None
    line_counters = {temp_id: 0 for temp_id in preprocessed_sections}
    all_sections_processed = False
    counter = 0

    while not all_sections_processed:
        all_sections_processed = True

        for temp_id, section_lines in preprocessed_sections.items():
            counter = line_counters[temp_id]
            zero_lines = []
            current_mat_mf_mt = None

            while counter < len(section_lines):
                line = section_lines[counter]
                counter += 1

                # skip on empty line
                if line.strip() == '':
                    continue

                mat, mf, mt = extract_mat_mf_mt(line)

                if current_mat_mf_mt is None and mf != 0 and mt != 0:
                    current_mat_mf_mt = (mat, mf, mt)

                if is_zero_line(line):
                    zero_lines.append(line)

                if not is_zero_line(line) and (mat, mf, mt) != current_mat_mf_mt:
                    print("end section", current_mat_mf_mt, temp_id, temp_id == max(preprocessed_sections.keys()))
                    break
                line_counters[temp_id] = counter

                if not is_zero_line(line):
                    combined_lines.append(line)

                all_sections_processed = False
            
            # Append zero lines if this is the last section
            if temp_id == max(preprocessed_sections.keys()):
                combined_lines.extend(zero_lines)
                zero_lines = []

            # Reset for the next section
            if temp_id == max(preprocessed_sections.keys()):
                current_mat_mf_mt = None

    return '\n'.join(combined_lines) + '\n'

def make_pendfs(endf, **kwargs,):
    """
    Like get_pendf method from Endf6 class, but for pendf files with multiple temperatures.

    Args:
        endf (Endf6): The ENDF-6 object.
        **kwargs: Additional keyword arguments.

    Returns:
        Union[Endf6, Tuple[Endf6, Endf6]]: The output ENDF-6 object(s).
    """
    kwargs["acer"] = False

    with TemporaryDirectory() as td:
        endf6file = join(td, "endf6_file")
        endf.to_file(endf6file)
        outputs = sandy.njoy.process_neutron(
            endf6file,
            suffixes=[0],
            **kwargs,
            )
    if kwargs.get("dryrun", False):
        return outputs  # this contains the NJOY input
    # Split the output pendf and return endf objects
    return get_pendf_endf(outputs["pendf"])