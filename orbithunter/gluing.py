from .discretization import rediscretize, correct_aspect_ratios
from .io import read_h5
import numpy as np
import os
import itertools

__all__ = ['tile', 'glue']


# def best_combination(orbit, other_orbit, fundamental_domain_combinations, axis=0):
#     half_combinations = list(itertools.product(half_list,repeat=2))
#     residual_list = []
#     glued_list = []
#     for halves in half_combinations:
#         orbit_domain = orbit._to_fundamental_domain(half=halves[0])
#         other_orbit_domain = other_orbit._to_fundamental_domain(half=halves[1])
#         glued = concat(orbit_domain, other_orbit_domain, direction=direction)
#         glued_orbit = glued._from_fundamental_domain()
#         glued_list.extend([glued_orbit])
#         residual_list.extend([glued_orbit.residual])
#     best_combi = np.array(glued_list)[np.argmin(residual_list)]
#     return best_combi
#
#
# def best_rotation(orbit, other_orbit, axis=0):
#     field_orbit, field_other_orbit = correct_aspect_ratios(orbit, other_orbit, axis=axis)
#
#     resmat = np.zeros([field_other_orbit.N, field_other_orbit.M])
#     # The orbit only remains a converged solution if the rotations occur in
#     # increments of the discretization, i.e. multiples of L / M and T / N.
#     # The reason for this is because those are the only values that do not
#     # actually change the field via interpolation. In other words,
#     # The rotations must coincide with the collocation points.
#     # for n in range(0, field_other_orbit.N):
#     #     for m in range(0, field_other_orbit.M):
#     #         rotated_state = np.roll(np.roll(field_other_orbit.state, m, axis=1), n, axis=0)
#     #         rotated_orbit = other_orbit.__class__(state=rotated_state, state_type=field_other_orbit.state_type, T=other_orbit.T,
#     #                                               L=other_orbit.L, S=other_orbit.S)
#     #         resmat[n,m] = concat(field_orbit, rotated_orbit, direction=direction).residual
#
#
#     bestn, bestm = np.unravel_index(np.argmin(resmat), resmat.shape)
#     high_resolution_orbit = rediscretize(field_orbit, new_N=16*field_orbit.N, new_M=16*field_orbit.M)
#     high_resolution_other_orbit = rediscretize(field_other_orbit, new_N=16*field_other_orbit.N, new_M=16*field_other_orbit.M)
#
#     best_rotation_state = np.roll(np.roll(high_resolution_other_orbit.state, 16*bestm, axis=1), 16*bestn, axis=0)
#     highres_rotation_orbit = other_orbit.__class__(state=best_rotation_state, state_type='field',
#                                                    T=other_orbit.T, L=other_orbit.L, S=other_orbit.S)
#     best_gluing = concat(high_resolution_orbit, highres_rotation_orbit, direction=direction)
#     return best_gluing

# def combine(orbit, other_orbit, axis=0):
#     # Converts tori to best representatives for gluing by choosing from group orbit.
#     continuous_classes = ['Orbit', 'RelativeOrbit']
#     discrete_classes = ['ShiftReflectionOrbit', 'AntisymmetricOrbit']
#     orbit_name = orbit.__class__.__name__
#     other_name = other_orbit.__class__.__name__
#     if (orbit_name in continuous_classes) and (other_name in continuous_classes):
#         return best_rotation(orbit, other_orbit, direction=direction)
#     elif (orbit_name in discrete_classes) and (other_name in discrete_classes):
#         return best_combination(orbit, other_orbit, direction=direction)
#     else:
#         return concat(orbit, other_orbit, direction=direction)


def tile_dictionary_ks(padded=False, comoving=False):
    if padded:
        directory = os.path.join(os.path.abspath(os.path.join(os.getcwd(), '../data/tiles/padded/')), '')
    else:
        directory = os.path.join(os.path.abspath(os.path.join(os.getcwd(), '../data/tiles/')), '')

    if comoving:
        # padded merger Orbit in comoving frame
        merger = read_h5(os.path.abspath(os.path.join(directory, "./OrbitKS_merger.h5")))
    else:
        # padded merger orbit in physical frame.
        merger = read_h5(os.path.abspath(os.path.join(directory, "./OrbitKS_merger_fdomain.h5")))

    # padded streak orbit
    streak = read_h5(os.path.abspath(os.path.join(directory, "./OrbitKS_streak.h5")))

    # padded wiggle orbit
    wiggle = read_h5(os.path.abspath(os.path.join(directory, "./OrbitKS_wiggle.h5")))

    tile_dict = {0: streak, 1: merger, 2: wiggle}
    return tile_dict


def glue(array_of_orbits, class_constructor, **kwargs):
    """ Function for combining spatiotemporal fields

    Parameters
    ----------
    array_of_orbits : ndarray of Orbit instances
        A NumPy array wherein each element is an orbit. i.e. a tensor of Orbit instances. The shape should be
        representative to how the orbits are going to be glued. See notes for more details. The orbits must all
        have the same discretization size if gluing is occuring along more than one axis. The orbits should
        all be in the physical field basis.
    class_constructor : Orbit class
        i.e. OrbitKS without parentheses

    Returns
    -------
    glued_orbit : Orbit instance
        Instance of type class_constructor

    Notes
    -----
    Assumes that each orbit in the array has identical dimensions in all other axes other than the one specified.
    Assumes no symmetries of the different orbits in the array. There are too many complications if handled otherwise.

    Because of how the concatenation of fields works, wherein the discretization must match along the boundaries. It
    is quite complicated to write a generalized code that glues all dimensions together at once, so instead this is
    designed to iterate through the axes of the array_of_orbits.

    To prevent confusion, there are many different "shapes" and discretizations that are possibly floating around.
    There are three main array shapes or dimensions that are involved in this function. The first is the array
    of orbits, which represents a spatiotemporal symbolic "dynamics" block. This array can have as many dimensions
    as the solutions to the equation have. An array of orbits of shape (2,1,1,1) means that the fields have four
    continuous dimensions; they need not be scalar fields either. The specific shape means that two such fields
    are being concatenated in time (because the first axis should always be time).

    Example for the spatiotemporal Navier-stokes equation. The spacetime is (1+3) dimensional. Let's assume we're gluing
    two vector fields with the same discretization size, (N, X, Y, Z). We can think of this discretization as a collection
    of 3D vector field snapshots in time. Therefore, there are actually (N, X, Y, Z, 3) degrees of freedom. Therefore
    the actually tensor before the gluing will be of the shape (2, 1, 1, 1, N, X, Y, Z, 3). Because we are gluing the
    orbits along the time axis, The final shape will be (1, 1, 1, 1, 2*N, X, Y, Z, 3), given that the original
    X, Y, Z, are all the same size. Being forced to have everything the same size is what makes this difficult, because
    this dramatically complicates things for a multi-dimensional symbol array.

    It's so complicated that for gluing along more than one axis its only really viable to start with tiles with the
    same shape.

    For a symbol array of shape (a, b, c, d) and orbit field with shape (N, X, Y, Z, 3) the final dimensions
    would be (a*N, b*X, c*Y, d*Z, 3). I believe that this can be achieved by repeated concatenation along the
    axis corresponding to the last axis of the symbol array. i.e. for (a,b,c,d) this would be concatenation along
    axis=3, 4 times in a row. I believe that this generalizes for all equations but it's hard to test

    """
    glue_shape = array_of_orbits.shape
    state_shape = array_of_orbits.ravel()[0].parameters['field_shape']
    # This joins the dictionary of all orbits' dimensions by zipping the values together. i.e.
    # {'T': T_1, 'L': L_1}, {'T': T_2, 'L': L_2}, .....  transforms into  {'T': (T_1, T_2, ...) , 'L': (L_1, L_2, ...)}
    zipped_parameter_dict = dict(zip(class_constructor.dimensions(),
                                     zip(*(tuple(o.parameters[dim] for dim in class_constructor.dimensions())
                                           for o in array_of_orbits.ravel())
                                         )
                                     ))
    zipped_parameter_dict2 = dict(zip(class_constructor.dimensions(),
                                     zip(*(o.field_dimensions() for o in array_of_orbits.ravel()))
                                     ))
    glued_parameters = class_constructor.glue_parameters(zipped_parameter_dict, glue_shape=glue_shape)
    # If only gluing in one dimension, we can better approximate by using the correct aspect ratios
    # in the gluing dimension.
    if glue_shape.count(1) == len(glue_shape)-1:
        gluing_axis = np.argmax(glue_shape)
        array_of_orbits = correct_aspect_ratios(array_of_orbits.ravel(), axis=gluing_axis)
        orbit_field_list = [o.convert(to='field').state for o in array_of_orbits]
        glued_orbit_state = np.concatenate(orbit_field_list, axis=gluing_axis)
    else:
        gluing_axis = len(glue_shape) - 1
        orbit_field_list = [o.convert(to='field').state for o in array_of_orbits.ravel()]
        glued_orbit_state = np.array(orbit_field_list).reshape(*array_of_orbits.shape, *state_shape)

        while len(glued_orbit_state.shape) > len(state_shape):
            glued_orbit_state = np.concatenate(glued_orbit_state, axis=gluing_axis)

    glued_orbit = class_constructor(state=glued_orbit_state, state_type='field',
                                    parameters=glued_parameters, **kwargs)
    return glued_orbit


def tile(symbol_array, tiling_dictionary, class_constructor, tile_shape=(64, 64), **kwargs):
    """
    Parameters
    ----------
    symbol_array : ndarray
        An array of dictionary keys which exist in tiling_dictionary
    tiling_dictionary : dict
        A dictionary whose values are Orbit instances.
    class_constructor : Orbit generator
        i.e. Orbit w/o parenthesis.
    tile_shape : tuple
        Tuple containing the field discretization to be used in tiling
    kwargs :
        Orbit kwargs relevant to instantiation
    Returns
    -------

    """
    symbol_array_shape = symbol_array.shape
    array_of_orbits = np.array([rediscretize(tiling_dictionary[symbol], new_shape=tile_shape)
                                for symbol in symbol_array.ravel()]).reshape(*symbol_array_shape)
    glued_orbit = glue(array_of_orbits, class_constructor, **kwargs)
    return glued_orbit


def query_symbolic_index(symbol_array, results_csv):
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
    from pandas import read_csv

    all_rotations = itertools.product(*(list(range(a)) for a in symbol_array.shape))
    axes = tuple(range(len(symbol_array.shape)))
    equivariant_symbol_string_list = []
    for rotation in all_rotations:
        equivariant_symbol_string_list.append(to_symbol_string(np.roll(symbol_array, rotation, axis=axes)))

    results_data_frame = read_csv(results_csv, index_col=0)
    n_permutations_in_results_log = results_data_frame.index.isin(equivariant_symbol_string_list).sum()
    return n_permutations_in_results_log


def to_symbol_string(symbol_array):
    symbolic_string = symbol_array.astype(str).copy()
    shape_of_axes_to_contract = symbol_array.shape[1:]
    for i, shp in enumerate(shape_of_axes_to_contract):
        symbolic_string = [(i*'_').join(list_) for list_ in np.array(symbolic_string).reshape(-1, shp).tolist()]
    symbolic_string = ((len(shape_of_axes_to_contract))*'_').join(symbolic_string)
    return symbolic_string


def to_symbol_array(symbol_string, symbol_array_shape):
    return np.array([char for char in symbol_string.replace('_', '')]).astype(int).reshape(symbol_array_shape)


