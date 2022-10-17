import re
import sys
from random import choices
from string import ascii_letters
from os import mkdir, rmdir, remove, replace, environ
from os.path import join, isfile
from subprocess import run
from shutil import copy
from concurrent.futures import ProcessPoolExecutor
from ase.io import write

# Files that xtb can create that I may have to remove in the cleanup step
# Just grepped "file="
possible_files_xtb = ["charges", "charges2", "charges3", "wbo", "wbo3", "wbofit",
        "spin", "spin3", "dipole", "dipole2", "energy", "pcharge", "fod",
        "hfc3"]
# Same thing but from stda
possible_files_stda = ["TmPvEcInFo", "qia", "zmint", "xlint", "beta_HRS",
                       "tday.dat", "tdaz.dat", "qaa", "1st_sf_MO.molden",
                       "NTOvar", "pij", "molden.input", ".REF", "NTOspin",
                       "~/.param", "NTOs.html", "yvint", "NTOat", "bmat",
                       "tdax.dat", "zlint", "qii", "qab", "molden.molden",
                       "xmint", "zvint", "beta_tensor", "qij", "tda.dat",
                       "xvint", "NTOao", ".STDA", "tda.exc", "ylint", "ymint",
                       ".OUT", "amb", "wavelength", "wfn.xtb", "fnorm", "sint",
                       "2PA-abs", ".ref", "apbmat", "pia", "jmol.spt"]
default_param_v_text = open(join(__path__[0], "param_v_template.txt")).read()
default_param_x_text = open(join(__path__[0], "param_x_template.txt")).read()

def save_wavefunction(mol, outpath,
                      param_x_text = default_param_x_text,
                      param_v_text = default_param_v_text,
                      nthreads = None):
    '''Given an ASE molecule, save an XTB wavefunction to the given directory,
    computed using xtb4stda'''

    # Create temporary directory with a random name
    temp_dir_name = "tempdir_" + "".join(choices(ascii_letters, k = 80))
    mkdir(temp_dir_name)

    # Save parameter files
    param_x_path = join(temp_dir_name, "param_x.xtb")
    open(param_x_path, "w").write(param_x_text)
    param_v_path = join(temp_dir_name, "param_v.xtb")
    open(param_v_path, "w").write(param_v_text)

    # Save xyz file
    xyz_path = join(temp_dir_name, "mol.xyz")
    write(xyz_path, mol)

    # Set environment variables
    env = environ.copy()
    if nthreads is not None:
        env["OMP_NUM_THREADS"] = str(nthreads)
        env["MKL_NUM_THREADS"] = str(nthreads)
    # Set working directory to target folder and run
    run(["xtb4stda", "mol.xyz", "-parx", "param_x.xtb", "-parv", "param_v.xtb"],
        cwd = temp_dir_name, check = True, env = env)

    # Copy wavefunction file to target path
    temp_wavefunction_path = join(temp_dir_name, "wfn.xtb")
    replace(temp_wavefunction_path, outpath)

    # Cleanup
    for temp_file_name in possible_files_xtb:
        temp_file_path = join(temp_dir_name, temp_file_name)
        if isfile(temp_file_path):
            remove(temp_file_path)
    remove(xyz_path)
    remove(param_x_path)
    remove(param_v_path)
    # After moving the wavefuntion file and deleting the molecule and the extra
    # files generated by xtb4stda, the directory should be empty, so there
    # should be no error from rmdir
    rmdir(temp_dir_name)

def wavefunction_stda(xtb_path, dat_path = None, triplet = False, nthreads = None):
    '''Given a path to an XTB wavefunction created by xtb4stda, run stda and
    return the output as a string'''

    # Create temporary directory to store wavefunction.  This avoids conflicts
    # with other instances, since stda requires a specific name for the file
    temp_dir_name = "tempdir_" + "".join(choices(ascii_letters, k = 80))
    mkdir(temp_dir_name)

    # Copy the wavefunction file into the directory, with the name that the
    # stda program expects
    copied_xtb_path = join(temp_dir_name, "wfn.xtb")
    copy(xtb_path, copied_xtb_path)

    # Add extra flags to the subprocess command based on the optional function
    # parameters
    extra_flags = []
    if triplet:
        extra_flags.append("-t")

    # Set environment variables
    env = environ.copy()
    if nthreads is not None:
        env["OMP_NUM_THREADS"] = str(nthreads)
        env["MKL_NUM_THREADS"] = str(nthreads)

    # Run stda
    stda_run = run(["stda", "-xtb"] + extra_flags, capture_output = True, cwd =
                   temp_dir_name, check = True, text = True, env = env)

    # Retrieve text printed by the stda program
    out_text = stda_run.stdout

    # If we're keeping the dat file in order to make a spectrum with g_spec,
    # copy it to the given path
    if dat_path is not None:
        copy(join(temp_dir_name, "tda.dat"), dat_path)

    # Cleanup
    remove(copied_xtb_path)
    for temp_file_name in possible_files_stda:
        temp_file_path = join(temp_dir_name, temp_file_name)
        if isfile(temp_file_path):
            remove(temp_file_path)
    # After removing the input file and every possible output file, should be
    # clear to remove the directory
    rmdir(temp_dir_name)

    return out_text

# Copied from my script iridium_xtb_test/log2energy.py
def log2energy(stda_log):
    '''From an stda log as a string, extract and return the excitation energy
    to the lowest excited state as a number, in eV'''
    right_part = False
    for line in stda_log.split("\n"):
        match_string = r"\s*1\s*([.0-9]*)"
        # Section heading
        if "excitation energies, transition moments and TDA amplitudes" in line:
            right_part = True
        if line.strip() == "":
            right_part = False
        energy_match = re.match(match_string, line)
        if right_part and energy_match is not None:
            return float(energy_match.group(1))

def mol2energy(mol,
               # xtb4stda arguments
               param_x_text = default_param_x_text,
               param_v_text = default_param_v_text,
               nthreads = None,
               # stda arguments
               triplet = False):
    '''Convenience wrapper function that does xtb, stda, and extracts an energy
    from an ASE molecule, returning the energy in eV as a float'''
    # Name of temporary wavefunction file
    temp_file_name = "tmp_wfn_" + "".join(choices(ascii_letters, k = 80)) + ".xtb"
    save_wavefunction(mol, temp_file_name, param_x_text = param_x_text,
                      param_v_text = param_v_text, nthreads = nthreads)

    # Log from stda
    stda_log = wavefunction_stda(temp_file_name, triplet = triplet)
    remove(temp_file_name)

    # Energy
    return log2energy(stda_log)

class Mol2EnergyClosure:
    def __init__(self, 
               # xtb4stda arguments
               param_x_text = default_param_x_text,
               param_v_text = default_param_v_text,
               # stda arguments
               triplet = False):
        self.param_x_text = param_x_text
        self.param_v_text = param_v_text
        self.triplet = triplet
    
    def __call__(self, mol):
        return mol2energy(mol, param_x_text = self.param_x_text, param_v_text =
        self.param_v_text, triplet = self.triplet, nthreads = 1)

def mols2energy(mols,
               # xtb4stda arguments
               param_x_text = default_param_x_text,
               param_v_text = default_param_v_text,
               # stda arguments
               triplet = False):
    '''Given a list of ASE molecules, run xtb-stda on them in parallel, and
    return a list of excitation energies'''
    closure = Mol2EnergyClosure(
               param_x_text = param_x_text,
               param_v_text = param_v_text,
               triplet = triplet)
    with ProcessPoolExecutor() as pool:
        # Without calling "list", I get a generator
        energies = list(pool.map(closure, mols))
    return energies
