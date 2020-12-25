import os
import numpy as np
import pandas as pd
import itertools
import h5py
import importlib

# TODO : tilesets, iterable loading.


__all__ = ['read_h5', 'read_tileset', 'convergence_log', 'refurbish_log', 'write_symbolic_log',
           'read_symbolic_log', 'to_symbol_string', 'to_symbol_array']


def read_h5(path, h5_groups, equation, class_name=None, validate=False, **orbitkwargs):
    """
    Parameters
    ----------
    path : str
        Absolute or relative path to .h5 file
    h5_groups : str or tuple of str
        The h5py.Group (s) of the corresponding .h5 file
    equation : str
        The abbreviation for the corresponding equation's module.
    class_name : str or iterable of str
        If iterable of str then it needs to be the same length as h5_groups
    validate : bool
        Whether or not to access Orbit().verify_integrity, presumably checking the integrity of the imported data.
    orbitkwargs : dict
        Any additional keyword arguments relevant for instantiation.

    Returns
    -------
    Orbit :
        The imported

    Notes
    -----
    h5_group can either be a single string or an iterable; this is to make importation of multiple .h5 files
    more efficient, i.e. avoiding multiple dynamic imports of the same package.

    """
    # The following loads the module for the correct equation dynamically when the function is called, to prevent
    # imports of all equations and possible circular dependencies.
    module = importlib.import_module(''.join(['.', equation]), 'orbithunter')

    if isinstance(h5_groups, str):
        # If string, then place inside a len==1 tuple so that iteration doesn't raise an error
        h5_groups = (h5_groups,)
    elif isinstance(h5_groups, tuple) and len(h5_groups) > 1:
        # If tuple, but len > 1 then this implies that *args were passed separated by commas, i.e. a,b,c as opposed
        # to (a,b,c)
        pass
    else:
        raise TypeError('Incorrect type for hdf5 group names; needs to be str separated by commas or a tuple of str')

    # With h5_groups now correctly instantiated as an iterable, can open file and iterate.
    with h5py.File(os.path.abspath(path), 'r') as file:
        imported_orbits = []
        for i, orbit_group in enumerate(h5_groups):
            # class_name needs to be constant (str input) or specified for each group (tuple with len == len(h5_groups))
            try:
                if isinstance(class_name, str):
                    class_ = getattr(module, class_name)
                elif isinstance(class_name, tuple):
                    class_ = getattr(module, class_name[i])
                elif class_name is None:
                    # If the class generator is not provided, it is assumed to be able to be inferred from the filename.
                    # This is simply a convenience tool because typically the classes are the best partitions of the
                    # full data set.
                    class_ = getattr(module, str(os.path.basename(path).split('.h5')[0].split('_')[0]))
            except (NameError, TypeError, IndexError):
                print('class_name from read_h5() requires str, None(default), or a tuple the same length as h5_groups')

            orbit_ = class_(state=file[''.join([orbit_group, '/field'])][...],
                            parameters=tuple(file[''.join([orbit_group, '/parameters'])]),
                            basis='field', **orbitkwargs)
            if validate:
                imported_orbits.append(orbit_.verify_integrity()[0])
            else:
                imported_orbits.append(orbit_)

    if len(imported_orbits) == 1:
        # If there is only a single orbit, return as orbit instance not list
        return imported_orbits[0]
    else:
        return imported_orbits


def read_tileset(path, equation, keys, h5_groups, class_name=None, validate=False, **orbitkwargs):
    """ Importation of data as tiling dictionary

    Parameters
    ----------
    path
    equation
    keys
    h5_groups
    class_name
    validate
    orbitkwargs

    Returns
    -------

    """
    orbits = read_h5(path, equation, h5_groups, class_name=class_name, validate=validate, **orbitkwargs)
    # if keys and orbits are not the same length, it will only form a dict with min([len(keys), len(orbits)]) items
    return dict(zip(keys, orbits))


def convergence_log(initial_orbit, converge_result, log_path, spectrum='random', method='adj'):
    initial_condition_log_ = pd.read_csv(log_path, index_col=0)
    # To store all relevant info as a row in a Pandas DataFrame, put into a 1-D array first.
    dataframe_row = [[initial_orbit.parameters, initial_orbit.field_shape,
                     np.abs(initial_orbit.transform(to='field').state).max(), converge_result.orbit.residual(),
                     converge_result.status, spectrum, method]]
    labels = ['parameters', 'field_shape', 'field_magnitude', 'residual', 'status', 'spectrum', 'numerical_method']
    new_row = pd.DataFrame(dataframe_row, columns=labels)
    initial_condition_log_ = pd.concat((initial_condition_log_, new_row), axis=0)
    initial_condition_log_.reset_index(drop=True).drop_duplicates().to_csv(log_path)
    return initial_condition_log_


def refurbish_log(orbit_, filename, log_filename, overwrite=False, **kwargs):
    if not os.path.isfile(log_filename):
        refurbish_log_ = pd.Series(filename).to_frame(name='filename')
    else:
        refurbish_log_ = pd.read_csv(log_filename, index_col=0)

    if not overwrite and filename in np.array(refurbish_log_.values).tolist():
        orbit_.to_h5(filename, **kwargs)
        orbit_.plot(filename=filename, **kwargs)
        refurbish_log_ = pd.concat((refurbish_log_, pd.Series(filename).to_frame(name='filename')), axis=0)
        refurbish_log_.reset_index(drop=True).drop_duplicates().to_csv(log_filename)


def write_symbolic_log(symbol_array, converge_result, log_filename, tileset='default',
                       comoving=False):
    symbol_string = to_symbol_string(symbol_array)
    dataframe_row_values = [[symbol_string, converge_result.orbit.parameters, converge_result.orbit.field_shape,
                             converge_result.orbit.residual(),
                             converge_result.status, tileset, comoving, symbol_array.shape]]
    labels = ['symbol_string', 'parameters', 'field_shape', 'residual', 'status', 'tileset',
              'comoving', 'tile_shape']

    dataframe_row = pd.DataFrame(dataframe_row_values, columns=labels).astype(object)
    log_path = os.path.abspath(os.path.join(__file__, '../../data/logs/', log_filename))

    if not os.path.isfile(log_path):
        file_ = dataframe_row.copy()
    else:
        file_ = pd.read_csv(log_path, dtype=object, index_col=0)
        file_ = pd.concat((file_, dataframe_row), axis=0)
    file_.reset_index(drop=True).drop_duplicates().to_csv(log_path)
    # To store all relevant info as a row in a Pandas DataFrame, put into a 1-D array first.
    return None


def read_symbolic_log(symbol_array, log_filename, overwrite=False, retry=False):
    """ Check to see if a combination has already been searched for locally.

    Returns
    -------

    Notes
    -----
    Computes the equivariant equivalents of the symbolic array being searched for.
    Strings can become arbitrarily long but I think this is unavoidable unless symbolic dynamics are redefined
    to get full shift.

    This checks the records/logs as to whether an orbit or one of its equivariant arrangements converged with
    a particular method.
    """
    all_rotations = itertools.product(*(list(range(a)) for a in symbol_array.shape))
    axes = tuple(range(len(symbol_array.shape)))
    equivariant_str = []
    for rotation in all_rotations:
        equivariant_str.append(to_symbol_string(np.roll(symbol_array, rotation, axis=axes)))

    log_path = os.path.abspath(os.path.join(__file__, '../../data/logs/', log_filename))
    if not os.path.isfile(log_path):
        return False
    else:
        symbolic_df = pd.read_csv(log_path, dtype=object, index_col=0)
        symbolic_intersection = symbolic_df[(symbolic_df['symbol_string'].isin(equivariant_str))].reset_index(drop=True)
        if len(symbolic_intersection) == 0:
            return False
        elif overwrite:
            return False
        # If success, then one of the 'status' values has been saves as -1. Count the number of negative ones
        # and see if there is indeed such a value.
        elif len(symbolic_intersection[symbolic_intersection['status'] == -1]) == 0 and retry:
            return False
        else:
            return True


def to_symbol_string(symbol_array):
    symbolic_string = symbol_array.astype(str).copy()
    shape_of_axes_to_contract = symbol_array.shape[1:]
    for i, shp in enumerate(shape_of_axes_to_contract):
        symbolic_string = [(i*'_').join(list_) for list_ in np.array(symbolic_string).reshape(-1, shp).tolist()]
    symbolic_string = ((len(shape_of_axes_to_contract))*'_').join(symbolic_string)
    return symbolic_string


def to_symbol_array(symbol_string, symbol_array_shape):
    return np.array([char for char in symbol_string.replace('_', '')]).astype(int).reshape(symbol_array_shape)
