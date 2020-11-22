from math import pi
from .arrayops import *
from ..core import Orbit
from scipy.fft import rfft, irfft
from scipy.linalg import block_diag
from mpl_toolkits.axes_grid1 import make_axes_locatable
from functools import lru_cache
import os
import numpy as np
import matplotlib.pyplot as plt

__all__ = ['OrbitKS', 'RelativeOrbitKS', 'ShiftReflectionOrbitKS', 'AntisymmetricOrbitKS', 'EquilibriumOrbitKS',
           'RelativeEquilibriumOrbitKS', 'ks_parsing_util', 'ks_fpo_dictionary']


class OrbitKS(Orbit):

    def __init__(self, state=None, basis='modes', parameters=(0., 0., 0.), **kwargs):
        """ Object that represents invariant 2-torus solution of the Kuramoto-Sivashinsky equation.

        Parameters
        ----------
        state : ndarray(dtype=float, ndim=2)
            Array which contains one of the following: velocity field,
            spatial Fourier modes, or spatiotemporal Fourier modes.
            If None then a randomly generated set of spatiotemporal modes
            will be produced.
        basis : str
            Which basis the array 'state' is currently in. Takes values
            'field', 's_modes', 'modes'.
        parameters : tuple

        **kwargs :
        N : int
            The lattice size in the temporal dimension.
        M : int
            The lattice size in the spatial dimension.

        constraints: dict
            Dictionary where the keys are `self.parameter_labels` and values are bools, namely, whether
            the dimensions/parameters are to be constrained during optimization.

        _parse_parameter kwargs :
            See the description of the aforementioned method.

        Raises
        ----------
        ValueError :
            If 'state' is not a NumPy array

        See Also
        --------


        Notes
        -----
        The 'state' is ordered such that when in the physical basis, the last row corresponds to 't=0'. This
        results in an extra negative sign when computing time derivatives. This convention was chosen
        because it is conventional to display positive time as 'up'. This convention prevents errors
        due to flipping fields up and down. The spatial shift parameter only applies to RelativeOrbitKS.
        Its inclusion in the base class is again a convention
        for exporting and importing data. If no state is None then a randomly generated state will be
        provided. It's dimensions will provide on the spatial and temporal periods unless provided
        as keyword arguments {N, M}.

        The `parameters' argument is always given as a len(parameters)=3 tuple, in-case of conversion between
        different symmetry sub-types.

        Examples
        --------
        """
        super().__init__(state=state, basis=basis, parameters=parameters, **kwargs)

    def __getattr__(self, attr):
        # Only called if self.attr is not found.
        try:
            if str(attr) in ['T', 'L', 'S']:
                return 0.0
            elif str(attr) == 'state':
                return None
            else:
                error_message = ' '.join([self.__class__.__name__, 'has no attribute called \' {} \''.format(attr)])
                raise AttributeError(error_message)
        except ValueError:
            print('Attribute is not of readable type')

    def state_vector(self):
        """ Vector which completely specifies the orbit, contains state information and parameters. """
        return np.concatenate((self.state.reshape(-1, 1),
                               np.array([[float(self.T)]]),
                               np.array([[float(self.L)]])), axis=0)

    def from_numpy_array(self, state_vector, **kwargs):
        """ Utility to convert from numpy array to orbithunter format for scipy wrappers.

        Parameters
        ----------
        state_vector : ndarray
            State vector containing state values (modes, typically) and parameters or optimization corrections thereof.

        kwargs :
            parameters : tuple
                If parameters from another Orbit instance are to overwrite the values within the state_vector
            parameter_constraints : dict
                constraint dictionary, keys are parameter_labels, values are bools
            OrbitKS or subclass kwargs : dict
                If special kwargs are required/desired for Orbit instantiation.
        Returns
        -------


        Notes
        -----
        Important: If parameters are passed as a keyword argument, they are appended to the numpy array,
        'state_array', via concatenation. The common usage of this function is to take the output of SciPy
        optimization functions which are in the form of numpy arrays and cast them as Orbit instances.
        """
        # If there are parameters_passed, then they are meant to be added to the state_array (i.e. we're taking
        # values from another orbit instance.
        mode_shape, mode_size = self.mode_shape, self.state.size
        modes = state_vector.ravel()[:mode_size]
        # We slice off the modes and the rest of the list pertains to parameters; note if the state_array had
        # parameters, and parameters were added by

        params_list = list(kwargs.pop('parameters', state_vector.ravel()[mode_size:].tolist()))
        parameters = tuple(params_list.pop(0) if not p and params_list else 0 for p in self.constraints.values())
        state_orbit = self.__class__(state=np.reshape(modes, mode_shape), basis='modes',
                                     parameters=parameters, **kwargs)
        return state_orbit

    def verify_integrity(self):
        """ Check whether the orbit converged to an equilibrium or close-to-zero solution
        """
        # Take the L_2 norm of the field, if uniformly close to zero, the magnitude will be very small.
        field_orbit = self.transform(to='field')

        # See if the L_2 norm is beneath a threshold value, if so, replace with zeros.
        if field_orbit.norm() < 10**-5:
            code = 4
            return EquilibriumOrbitKS(state=np.zeros([self.N, self.M]), basis='field',
                                      parameters=self.parameters).transform(to=self.basis), code
        # Equilibrium is defined by having no temporal variation, i.e. time derivative is a uniformly zero.
        elif self.T in [0., 0]:
            # If there is sufficient evidence that solution is an equilibrium, change its class
            code = 3
            # store T just in case we want to refer to what the period was before conversion to EquilibriumOrbitKS
            return EquilibriumOrbitKS(state=field_orbit.state, basis='field',
                                      parameters=self.parameters).transform(to=self.basis), code
        elif field_orbit.dt().transform(to='field').norm() < 10**-5:
            # If there is sufficient evidence that solution is an equilibrium, change its class
            code = 3
            # store T just in case we want to refer to what the period was before conversion to EquilibriumOrbitKS
            return EquilibriumOrbitKS(state=field_orbit.state, basis='field',
                                      parameters=self.parameters).transform(to=self.basis), code
        else:
            return self, 1

    def transform(self, inplace=False, to='modes'):
        """ Convert current state to a different basis.


        Parameters
        ----------
        inplace : bool
            Whether or not to perform the conversion "in place" or not.
        to : str
            One of the following: 'field', 's_modes', 'modes'. Specifies
            the basis which the orbit will be converted to. \
        Raises
        ----------
        ValueError
            Raised if the provided basis is unrecognizable.
        Returns
        ----------
        converted_orbit : orbit or orbit subclass instance
            The class instance in the new basis.

        Notes
        -----
        This instance method is just a wrapper for different
        Fourier transforms. It's purpose is to remove the
        need for the user to keep track of the basis by hand.
        This should be used as opposed to Fourier transforms.

        """
        if to == 'field':
            if self.basis == 's_modes':
                return self._inv_space_transform(inplace=inplace)
            elif self.basis == 'modes':
                return self._inv_spacetime_transform(inplace=inplace)
            else:
                return self
        elif to == 's_modes':
            if self.basis == 'field':
                return self._space_transform(inplace=inplace)
            elif self.basis == 'modes':
                return self._inv_time_transform(inplace=inplace)
            else:
                return self
        elif to == 'modes':
            if self.basis == 's_modes':
                return self._time_transform(inplace=inplace)
            elif self.basis == 'field':
                return self._spacetime_transform(inplace=inplace)
            else:
                return self
        else:
            raise ValueError('Trying to convert to unrecognizable state type.')

    def copy(self):
        """ Create another Orbit instance with a copy of the state array"""
        return self.__class__(state=self.state.copy(), basis=self.basis, parameters=self.parameters)

    def dot(self, other):
        """ Return the L_2 inner product of two orbits
        Returns
        -------
        float :
            The value of self * other via L_2 inner product.
        """
        return float(np.dot(self.state.ravel(), other.state.ravel()))

    def dt(self, power=1, return_array=False):
        """ Time derivatives of the current state.

        Parameters
        ----------
        power :int
            The order of the derivative.

        Returns
        ----------
        orbit_dtn : OrbitKS or subclass instance
            The class instance whose state is the time derivative in
            the spatiotemporal mode basis.
        """
        modes = self.transform(to='modes').state
        # Elementwise multiplication of modes with frequencies, this is the derivative.
        dtn_modes = np.multiply(self.elementwise_dtn(self.dt_parameters, power=power), modes)

        # If the order of the derivative is odd, then imaginary component and real components switch.
        if np.mod(power, 2):
            dtn_modes = swap_modes(dtn_modes, axis=0)

        if return_array:
            return dtn_modes
        else:
            orbit_dtn = self.__class__(state=dtn_modes, basis='modes', parameters=self.parameters)
            return orbit_dtn.transform(to=self.basis)

    def dx(self, power=1, **kwargs):

        """ A spatial derivative of the current state.

        Parameters
        ----------
        power :int
            The order of the derivative.

        Returns
        ----------
        orbit_dxn : OrbitKS or subclass instance
            Class instance whose spatiotemporal state represents the spatial derivative in the
            the basis of the original state.

        Notes
        -----
        Dimensions provided to np.tile in defining elementwise_dxn were originally (self.N-1, 1).
        """
        modes = self.transform(to='modes').state
        # Elementwise multiplication of modes with frequencies, this is the derivative.
        dxn_modes = np.multiply(self.elementwise_dxn(self.dx_parameters, power=power), modes)

        # If the order of the differentiation is odd, need to swap imaginary and real components.
        if np.mod(power, 2):
            dxn_modes = swap_modes(dxn_modes, axis=1)

        if kwargs.get('return_array', False):
            return dxn_modes
        else:
            orbit_dxn = self.__class__(state=dxn_modes, basis='modes', parameters=self.parameters)
            return orbit_dxn.transform(to=kwargs.get('basis', self.basis))

    @classmethod
    @lru_cache(maxsize=16)
    def elementwise_dxn(cls, dx_parameters, power=1):
        """ Matrix of temporal mode frequencies

        Creates and returns a matrix whose elements
        are the properly ordered spatial frequencies,
        which is the same shape as the spatiotemporal
        Fourier mode state. The elementwise product
        with a set of spatiotemporal Fourier modes
        is equivalent to taking a spatial derivative.

        Returns
        ----------
        matrix
            Matrix of spatial frequencies
        """

        q = cls._wave_vector(dx_parameters, power=power)
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        c1, c2 = so2_coefficients(power=power)
        # Create elementwise spatial frequency matrix
        dxn_multipliers = np.tile(np.concatenate((c1*q, c2*q), axis=1), (dx_parameters[-1], 1))
        return dxn_multipliers

    @classmethod
    @lru_cache(maxsize=16)
    def elementwise_dtn(cls, dt_parameters, power=1):
        """ Matrix of temporal mode frequencies

        Creates and returns a matrix whose elements
        are the properly ordered temporal frequencies,
        which is the same shape as the spatiotemporal
        Fourier mode state. The elementwise product
        with a set of spatiotemporal Fourier modes
        is equivalent to taking a time derivative.


        Returns
        ----------
        matrix
            Matrix of temporal frequencies
        """

        w = cls._frequency_vector(dt_parameters, power=power)
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        c1, c2 = so2_coefficients(power=power)
        # The Nyquist frequency is never included, this is how time frequency modes are ordered.
        # Elementwise product of modes with time frequencies is the spectral derivative.
        dtn_multipliers = np.tile(np.concatenate(([[0]], c1*w, c2*w), axis=0), (1, dt_parameters[-1]))
        return dtn_multipliers

    def from_fundamental_domain(self):
        """ This is a placeholder for the subclasses """
        return self

    def increment(self, other, step_size=1, **kwargs):
        """ Add optimization correction  to current state

        Parameters
        ----------
        other : OrbitKS
            Represents the values to increment by.
        step_size : float
            Multiplicative factor which decides the step length of the correction.

        Returns
        -------
        OrbitKS
            New instance which results from adding an optimization correction to self.
        """
        orbit_params = tuple(self_param + step_size * other_param for self_param, other_param
                             in zip(self.parameters, other.parameters))
        return self.__class__(state=self.state+step_size*other.state, basis=self.basis,
                              parameters=orbit_params,
                              constraints=self.constraints, **kwargs)

    def to_h5(self, filename=None, directory='local', verbose=False, include_residual=True):
        """ Export current state information to HDF5 file

        Notes
        -----
        Literally just to get a different default behavior for include_residual.
        """
        super().to_h5(filename=filename, directory=directory, verbose=verbose, include_residual=include_residual)
        return None

    def jacobian(self, **kwargs):
        """ Jacobian matrix evaluated at the current state.
        Parameters
        ----------
        parameter_constraints : tuple
            Determines whether to include period and spatial period
            as variables.
        Returns
        -------
        jac_ : matrix ((N-1)*(M-2), (N-1)*(M-2) + n_params)
            Jacobian matrix of the KSe where n_params = 2 - sum(parameter_constraints)

        Notes
        -----

        """

        self.transform(to='modes', inplace=True)
        # The Jacobian components for the spatiotemporal Fourier modes
        jac_ = self._jac_lin() + self._jac_nonlin()
        jac_ = self._jacobian_parameter_derivatives_concat(jac_)
        return jac_

    def norm(self, order=None):
        """ Norm of spatiotemporal state via numpy.linalg.norm

        Example
        -------
        L_2 distance between two states
        >>> (self - other).norm()
        """
        return np.linalg.norm(self.state.ravel(), ord=order)

    def matvec(self, other, **kwargs):
        """ Matrix-vector product of a vector with the Jacobian of the current state.

        Parameters
        ----------
        other : OrbitKS
            OrbitKS instance whose state represents the vector in the matrix-vector multiplication.
        parameter_constraints : tuple
            Determines whether to include period and spatial period
            as variables.
        preconditioning : bool
            Whether or not to apply (left) preconditioning P (Ax)

        Returns
        -------
        OrbitKS :
            OrbitKS whose state and other parameters result from the matrix-vector product.

        Notes
        -----
        Equivalent to computation of v_t + v_xx + v_xxxx + d_x (u .* v)

        """

        assert (self.basis == 'modes') and (other.basis == 'modes')
        self_field = self.transform(to='field')
        other_mode_component = other.__class__(state=other.state, parameters=self.parameters)
        other_field = other_mode_component.transform(to='field')

        # factor of two comes from differentiation of nonlinear term.
        matvec_modes = (other_mode_component.dt(return_array=True) + other_mode_component.dx(power=2, return_array=True)
                        + other_mode_component.dx(power=4, return_array=True)
                        + 2 * self_field.nonlinear(other_field, return_array=True))

        if not self.constraints['T']:
            # Compute the product of the partial derivative with respect to T with the vector's value of T.
            # This is typically an incremental value dT.
            matvec_modes += other.parameters[0] * (-1.0 / self.T) * self.dt(return_array=True)

        if not self.constraints['L']:
            # Compute the product of the partial derivative with respect to L with the vector's value of L.
            # This is typically an incremental value dL.
            dfdl = ((-2.0/self.L)*self.dx(power=2, return_array=True)
                    + (-4.0/self.L)*self.dx(power=4, return_array=True)
                    + (-1.0/self.L) * self_field.nonlinear(self_field, return_array=True))
            matvec_modes += other.parameters[1] * dfdl

        return self.__class__(state=matvec_modes, basis='modes', parameters=self.parameters)

    def _pad(self, size, axis=0):
        """ Increase the size of the discretization via zero-padding

        Parameters
        ----------
        size : int
            The new size of the discretization, must be an even integer
            larger than the current size of the discretization.
        dimension : str
            Takes values 'space' or 'time'. The dimension that will be padded.

        Returns
        -------
        OrbitKS :
            OrbitKS instance with larger discretization.

        Notes
        -----
        Need to account for the normalization factors by multiplying by old, dividing by new.

        """
        modes = self.transform(to='modes')
        if np.mod(size, 2):
            raise ValueError('New discretization size must be an even number, preferably a power of 2')
        else:
            if axis == 0:
                # Split into real and imaginary components, pad separately.
                first_half = modes.state[:-modes.n, :]
                second_half = modes.state[-modes.n:, :]
                padding_number = int((size-modes.N) // 2)
                padding = np.zeros([padding_number, modes.state.shape[1]])
                padded_modes = np.sqrt(size / modes.N) * np.concatenate((first_half, padding, second_half, padding),
                                                                        axis=0)
            else:
                # Split into real and imaginary components, pad separately.
                first_half = modes.state[:, :-modes.m]
                second_half = modes.state[:, -modes.m:]
                padding_number = int((size-modes.M) // 2)
                padding = np.zeros([modes.state.shape[0], padding_number])
                padded_modes = np.sqrt(size / modes.M) * np.concatenate((first_half, padding, second_half, padding),
                                                                        axis=1)

        return self.__class__(state=padded_modes, basis='modes',
                              parameters=self.parameters).transform(to=self.basis)

    def _truncate(self, size, axis=0):
        """ Decrease the size of the discretization via truncation

        Parameters
        -----------
        size : int
            The new size of the discretization, must be an even integer
            smaller than the current size of the discretization.
        dimension : str
            Takes values 'space' or 'time'. The dimension that will be truncated.

        Returns
        -------
        OrbitKS
            OrbitKS instance with larger discretization.
        """
        modes = self.transform(to='modes')
        if np.mod(size, 2):
            raise ValueError('New discretization size must be an even number, preferably a power of 2')
        else:
            if axis == 0:
                truncate_number = int(size // 2) - 1
                # Split into real and imaginary components, truncate separately.
                first_half = modes.state[:truncate_number+1, :]
                second_half = modes.state[-modes.n:-modes.n+truncate_number, :]
                truncated_modes = np.sqrt(size / modes.N) * np.concatenate((first_half, second_half), axis=0)
            else:
                truncate_number = int(size // 2) - 1
                # Split into real and imaginary components, truncate separately.
                first_half = self.state[:, :truncate_number]
                second_half = self.state[:, -self.m:-self.m + truncate_number]
                truncated_modes = np.sqrt(size / modes.M) * np.concatenate((first_half, second_half), axis=1)
        return self.__class__(state=truncated_modes, basis=self.basis, parameters=self.parameters)

    @property
    def dt_parameters(self):
        return self.T, self.N, self.n, self.M-2

    @property
    def dx_parameters(self):
        return self.L, self.M, self.m, max([self.N-1, 1])

    @property
    def parameters(self):
        return self.T, self.L, 0

    @staticmethod
    def dimension_labels():
        return 'T', 'L'

    @staticmethod
    def parameter_labels():
        return 'T', 'L', 'S'

    @property
    def field_shape(self):
        return self.N, self.M

    @property
    def mode_shape(self):
        return max([self.N-1, 1]), self.M-2

    @property
    def s_mode_shape(self):
        return self.N, self.M - 2

    @property
    def dimensions(self):
        return self.T, self.L

    @property
    def plotting_dimensions(self):
        return (0., self.T), (0., self.L / (2 * pi * np.sqrt(2)))

    @property
    def preconditioning_parameters(self):
        return self.dt_parameters, self.dx_parameters

    @classmethod
    def glue_parameters(cls, zipped_parameters, glue_shape=(1, 1)):
        """ Class method for handling parameters in gluing

        Parameters
        ----------
        parameter_dict_with_bundled_values : dict
        A dictionary whose values are a type which can be cast as a numpy.ndarray.
        axis

        glue_shape : tuple of ints
        The shape of the gluing being performed i.e. for a 2x2 orbit grid glue_shape would equal (2,2).

        Returns
        -------

        Notes
        -----
        Shift is always set to 0 at this point because it is based upon the field state being constructed.

        """
        T_array = np.array(zipped_parameters[0])
        L_array = np.array(zipped_parameters[1])

        if glue_shape[0] > 1 and glue_shape[1] == 1:
            glued_parameters = (np.sum(T_array), np.mean(L_array[L_array > 0.]), 0.)
        elif glue_shape[0] == 1 and glue_shape[1] > 1:
            # T_array.mean() not used because Tarray[T_array>0.] could be empty.
            glued_parameters = (T_array.sum()/max([1, len(T_array[T_array>0.])]), np.sum(L_array), 0.)
        elif glue_shape[0] > 1 and glue_shape[1] > 1:
            glued_parameters = (glue_shape[0] * T_array.sum()/max([1, len(T_array[T_array>0.])]),
                                glue_shape[1] * L_array.sum()/max([1, len(L_array[L_array>0.])]),
                                0.)
        else:
            # Gluing shouldn't really be used if there is literally no gluing occuring, i.e. glue_shape = (1,1),
            # but just for the sake of completeness.
            glued_parameters = (float(T_array), float(L_array), 0.)

        return glued_parameters

    @classmethod
    def parameter_based_discretization(cls, parameters, **kwargs):
        """ Follow orbithunter conventions for discretization size.


        Parameters
        ----------
        orbit : Orbit or Orbit subclass
        orbithunter class instance whose time, space periods will be used to determine the new discretization values.
        parameters : tuple
            tuple containing (T, L, S) i.e. OrbitKS().parameters
        kwargs :
        resolution : str
        Takes values 'coarse', 'normal', 'fine'. These options return one of three orbithunter conventions for the
        discretization size.

        Returns
        -------
        int, int
        The new spatiotemporal field discretization; number of time points (rows) and number of space points (columns)

        Notes
        -----
        This function should only ever be called by rediscretize, the returned values can always be accessed by
        the appropriate attributes of the rediscretized orbit_.
        """
        resolution = kwargs.get('resolution', 'normal')
        T, L = parameters[:2]
        if kwargs.get('N', None) is None:
            if T in [0, 0.]:
                N = 1
            elif isinstance(resolution, tuple):
                N = np.max([2**(int(np.log2(T)+resolution[0])), 16])
            elif resolution == 'coarse':
                N = np.max([2**(int(np.log2(T)-2)), 16])
            elif resolution == 'fine':
                N = np.max([2**(int(np.log2(T)+1)), 32])
            elif resolution == 'power':
                N = np.max([2*(int(4*T**(1./2.))//2), 32])
            else:
                N = np.max([2**(int(np.log2(T)-1)), 32])
        else:
            N = kwargs.get('N', None)

        if kwargs.get('M', None) is None:
            if isinstance(resolution, tuple):
                M = np.max([2**(int(np.log2(L)+resolution[1])), 16])
            elif resolution == 'coarse':
                M = np.max([2**(int(np.log2(L)-1)), 16])
            elif resolution == 'fine':
                M = np.max([2**(int(np.log2(L)+2)), 32])
            elif resolution == 'power':
                M = np.max([2*(int(4*L**(1./2.))//2), 32])
            else:
                M = np.max([2**(int(np.log2(L)+0.5)), 32])
        else:
            M = kwargs.get('M', None)
        return N, M

    def plot(self, show=True, save=False, fundamental_domain=False, **kwargs):
        """ Plot the velocity field as a 2-d density plot using matplotlib's imshow

        Parameters
        ----------
        show : bool
            Whether or not to display the figure
        save : bool
            Whether to save the figure
        padding : bool
            Whether to interpolate with zero padding before plotting. (Increases the effective resolution).
        fundamental_domain : bool
            Whether to plot only the fundamental domain or not.
        **kwargs :
            new_shape : (int, int)
                The field discretization to plot, will be used instead of default padding if padding is enabled.
            filename : str
                The (custom) save name of the figure, if save==True. Save name will be generated otherwise.
            directory : str
                The location to save to, if save==True
        Notes
        -----
        new_N and new_M are accessed via .get() because this is the only manner in which to incorporate
        the current N and M values as defaults.

        """
        verbose = kwargs.get('verbose', False)
        if np.product(self.field_shape) >= 256**2:
            padding = kwargs.get('padding', False)
        else:
            padding = kwargs.get('padding', True)
        plt.rc('text', usetex=True)
        plt.rc('font', family='serif')
        plt.rcParams['text.usetex'] = True

        if padding:
            padding_shape = kwargs.get('padding_shape', (16*self.N, 16*self.M))
            plot_orbit = self.reshape(padding_shape)
        else:
            plot_orbit = self.copy()

        if fundamental_domain:
            plot_orbit = plot_orbit.to_fundamental_domain().transform(to='field', inplace=True)
        else:
            # The fundamental domain is never used in computation, so no operations are required if we do not want
            # to plot the fundamental domain explicitly.
            plot_orbit = plot_orbit.transform(to='field', inplace=True)

        # The following creates custom tick labels and accounts for some pathological cases
        # where the period is too small (only a single label) or too large (many labels, overlapping due
        # to font size) Default label tick size is 10 for time and the fundamental frequency, 2 pi sqrt(2) for space.

        # Create time ticks, with the separation
        if plot_orbit.T > 10:
            timetick_step = np.max([np.min([100, (5 * 2**(np.max([int(np.log2(plot_orbit.T//2)) - 3,  1])))]), 5])
            yticks = np.arange(0, plot_orbit.T, timetick_step)
            ylabels = np.array([str(int(y)) for y in yticks])
        elif 0 < plot_orbit.T < 10:
            scaled_T = np.round(plot_orbit.T, 1)
            yticks = np.array([0, plot_orbit.T])
            ylabels = np.array(['0', str(scaled_T)])
        else:
            plot_orbit.T = np.min([plot_orbit.L, 1])
            yticks = np.array([0, plot_orbit.T])
            ylabels = np.array(['0', '$\\infty$'])

        if plot_orbit.L > 2*pi*np.sqrt(2):
            xmult = (plot_orbit.L // 64) + 1
            xscale = xmult * 2*pi*np.sqrt(2)
            xticks = np.arange(0, plot_orbit.L, xscale)
            xlabels = [str(int((xmult*x) // xscale)) for x in xticks]
        else:
            scaled_L = np.round(plot_orbit.L / (2*pi*np.sqrt(2)), 1)
            xticks = np.array([0, plot_orbit.L])
            xlabels = np.array(['0', str(scaled_L)])

        default_figsize = (min([max([0.25, 0.15*plot_orbit.L**0.7]), 20]), min([max([0.25, 0.15*plot_orbit.T**0.7]), 20]))

        figsize = kwargs.get('figsize', default_figsize)
        extentL, extentT = np.min([15, figsize[0]]), np.min([15, figsize[1]])
        scaled_font = np.max([int(np.min([20, np.mean(figsize)])), 10])
        plt.rcParams.update({'font.size': scaled_font})

        fig, ax = plt.subplots(figsize=(extentL, extentT))
        image = ax.imshow(plot_orbit.state, extent=[0, extentL, 0, extentT],
                          cmap='jet', interpolation='none', aspect='auto')

        xticks = (xticks/plot_orbit.L) * extentL
        yticks = (yticks/plot_orbit.T) * extentT

        # Include custom ticks and tick labels
        ax.set_xticks(xticks)
        ax.set_yticks(yticks)
        ax.set_xticklabels(xlabels, ha='left')
        ax.set_yticklabels(ylabels, va='center')
        ax.grid(True, linestyle='dashed', color='k', alpha=0.8)

        # Custom colorbar values
        maxu = round(np.max(plot_orbit.state.ravel()) - 0.1, 2)
        minu = round(np.min(plot_orbit.state.ravel()) + 0.1, 2)

        cbarticks = [minu, maxu]
        cbarticklabels = [str(i) for i in np.round(cbarticks, 1)]
        fig.subplots_adjust(right=0.95)
        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size=0.075, pad=0.1)
        cbar = plt.colorbar(image, cax=cax, ticks=cbarticks)
        cbar.ax.set_yticklabels(cbarticklabels, fontdict={'fontsize': scaled_font})

        filename = kwargs.get('filename', None)
        if save or (filename is not None):
            extension = kwargs.get('extension', '.png')
            directory = kwargs.get('directory', 'local')
            # Create save name if one doesn't exist.
            if filename is None:
                filename = self.parameter_dependent_filename(extension=extension)
            elif filename.endswith('.h5'):
                filename = filename.split('.h5')[0] + extension

            if fundamental_domain and str(plot_orbit) != 'OrbitKS':
                # Need to rename fundamental domain or else it will overwrite, of course there
                # is no such thing for solutions without any symmetries.
                filename = filename.split('.')[0] + '_fdomain.' + filename.split('.')[1]

            # Create save directory if one doesn't exist.
            if isinstance(directory, str):
                if directory == 'local':
                    directory = os.path.abspath(os.path.join(__file__, '../../../data/local/', str(self)))

            # If filename is provided as an absolute path it overrides the value of 'directory'.
            filename = os.path.abspath(os.path.join(directory, filename))

            if verbose:
                print('Saving figure to {}'.format(filename))
            plt.savefig(filename, bbox_inches='tight', pad_inches=0.05)

        if show:
            plt.show()

        plt.close()
        return None

    def mode_plot(self, scale='log'):
        """ Plot the velocity field as a 2-d density plot using matplotlib's imshow

        Parameters
        ----------
        show : bool
            Whether or not to display the figure
        save : bool
            Whether to save the figure
        padding : bool
            Whether to interpolate with zero padding before plotting. (Increases the effective resolution).
        fundamental_domain : bool
            Whether to plot only the fundamental domain or not.
        **kwargs :
            new_shape : (int, int)
                The field discretization to plot, will be used instead of default padding if padding is enabled.
            filename : str
                The (custom) save name of the figure, if save==True. Save name will be generated otherwise.
            directory : str
                The location to save to, if save==True
        Notes
        -----
        new_N and new_M are accessed via .get() because this is the only manner in which to incorporate
        the current N and M values as defaults.

        """
        plt.rc('text', usetex=True)
        plt.rc('font', family='serif')
        plt.rcParams['text.usetex'] = True

        if scale=='log':
            modes = np.log10(np.abs(self.transform(to='modes').state))
        else:
            modes = self.transform(to='modes').state

        fig, ax = plt.subplots()
        image = ax.imshow(modes, interpolation='none', aspect='auto')

        # Custom colorbar values
        fig.subplots_adjust(right=0.95)
        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size=0.075, pad=0.1)
        plt.colorbar(image, cax=cax)
        plt.show()

        return None

    def precondition(self, parameters, **kwargs):
        """ Precondition a vector with the inverse (absolute value) of linear spatial terms

        Parameters
        ----------
        parameters : tuple

        Returns
        -------
        target : OrbitKS
            Return the OrbitKS instance, modified by preconditioning.

        Notes
        -----
        Often we want to precondition a state derived from a mapping or rmatvec (gradient descent step),
        with respect to another orbit's (current state's) parameters. By passing parameters we can access the
        cached classmethods.

        I never preconditioned the spatial shift for relative periodic solutions so I don't include it here.
        """
        dt_params, dx_params = parameters
        p_multipliers = 1.0 / (np.abs(self.elementwise_dtn(dt_params))
                               + np.abs(self.elementwise_dxn(dx_params, power=2))
                               + self.elementwise_dxn(dx_params, power=4))
        self.state = np.multiply(self.state, p_multipliers)
        # Precondition the change in T and L
        param_powers = kwargs.get('pexp', (1, 1))
        if not self.constraints['T']:
            # self is the orbit being preconditioned, i.e. the correction orbit; by default this is dT = dT / T
            self.T = self.T * (dt_params[0]**-param_powers[0])

        if not self.constraints['L']:
            # self is the orbit being preconditioned, i.e. the correction orbit; by default this is dL = dL / L^4
            self.L = self.L * (dx_params[0]**-param_powers[1])

        return self

    def precondition_matvec(self, parameters, **kwargs):
        """ Preconditioning operation for the normal equations

        Parameters
        ----------
        parameters : tuple

        Returns
        -------
        target : OrbitKS
            Return the OrbitKS instance, modified by preconditioning.

        Notes
        -----
        Precondition applied twice because it is attempting to approximate the inverse M = (A^T A)^-1 not just A.
        """
        return self.precondition(parameters, **kwargs).precondition(parameters, **kwargs)

    def precondition_rmatvec(self, parameters, **kwargs):
        """ Precondition a vector with the inverse (absolute value) of linear spatial terms

        Parameters
        ----------
        parameters : tuple

        Returns
        -------
        target : OrbitKS
            Return the OrbitKS instance, modified by preconditioning.

        Notes
        -----
            Diagonal preconditioning implies rmatvec and matvec are the same, by definition.
        """
        return self.precondition_matvec(parameters, **kwargs)

    def reshape(self, *new_shape, **kwargs):
        """

        Parameters
        ----------
        new_shape : tuple of ints or None
        kwargs

        Returns
        -------

        """
        placeholder_orbit = self.transform(to='field').copy().transform(to='modes', inplace=True)
        if len(new_shape) == 1:
            # if passed as tuple, .reshape((a,b)), then need to unpack ((a, b)) into (a, b)
            new_shape = tuple(*new_shape)
        elif not new_shape:
            # if nothing passed, then new_shape == () which evaluates to false.
            # The default behavior for this will be to modify the current discretization
            # to a `parameter based discretization'. If this is not desired then simply do not call reshape.
            new_shape = self.parameter_based_discretization(self.parameters, **kwargs)

        if self.field_shape == new_shape:
            # to avoid unintended overwrites, return a copy.
            return self.copy()
        else:
            for i, d in enumerate(new_shape):
                if d < self.field_shape[i]:
                    placeholder_orbit = placeholder_orbit._truncate(d, axis=i)
                elif d > self.field_shape[i]:
                    placeholder_orbit = placeholder_orbit._pad(d, axis=i)
                else:
                    pass
            return placeholder_orbit.transform(to=self.basis, inplace=True)

    def rmatvec(self, other, **kwargs):
        """ Matrix-vector product with the adjoint of the Jacobian

        Parameters
        ----------
        other : OrbitKS
            OrbitKS whose state represents the vector in the matrix-vector product.
        parameter_constraints : (bool, bool)
            Whether or not period T or spatial period L are fixed.
        preconditioning : bool
            Whether or not to apply (left) preconditioning to the adjoint matrix vector product.

        Returns
        -------
        orbit_rmatvec :
            OrbitKS with values representative of the adjoint-vector product

        Notes
        -----
        The adjoint vector product in this case is defined as J^T * v,  where J is the jacobian matrix. Equivalent to
        evaluation of -v_t + v_xx + v_xxxx  - (u .* v_x). In regards to preconditioning (which is very useful
        for certain numerical methods, right preconditioning and left preconditioning switch meanings when the
        jacobian is transposed. i.e. Right preconditioning of the Jacobian can include preconditioning of the state
        parameters (which in this case are usually incremental corrections dT, dL, dS);
        this corresponds to LEFT preconditioning of the adjoint.

        """

        assert (self.basis == 'modes') and (other.basis == 'modes')
        self_field = self.transform(to='field')
        rmatvec_modes = (-1.0 * other.dt(return_array=True) + other.dx(power=2, return_array=True)
                         + other.dx(power=4, return_array=True)
                         + self_field.rnonlinear(other, return_array=True))

        # parameters are derived by multiplying partial derivatives w.r.t. parameters with the other orbit.
        rmatvec_params = self.rmatvec_parameters(self_field, other)

        return self.__class__(state=rmatvec_modes, basis='modes', parameters=rmatvec_params)

    def rmatvec_parameters(self, self_field, other):
        other_modes_in_vector_form = other.state.ravel()
        if not self.constraints['T']:
            # original
            rmatvec_T = (-1.0 / self.T) * self.dt(return_array=True).ravel().dot(other_modes_in_vector_form)
        else:
            rmatvec_T = 0

        if not self.constraints['L']:
            # change in L, dL, equal to DF/DL * v
            # original
            rmatvec_L = ((-2.0 / self.L) * self.dx(power=2, return_array=True)
                         + (-4.0 / self.L) * self.dx(power=4, return_array=True)
                         + (-1.0 / self.L) * self_field.nonlinear(self_field, return_array=True)
                         ).ravel().dot(other_modes_in_vector_form)
        else:
            rmatvec_L = 0

        return rmatvec_T, rmatvec_L, 0.

    def preconditioner(self, parameters, **kwargs):
        """ Preconditioning matrix

        Parameters
        ----------
        parameter_constraints : (bool, bool)
            Whether or not period T or spatial period L are fixed.
        side : str
            Takes values 'left' or 'right'. This is an accomodation for
            the typically rectangular Jacobian matrix.

        Returns
        -------
        matrix :
            Preconditioning matrix

        """
        # Preconditioner is the inverse of the absolute value of the linear spatial derivative operators.
        side = kwargs.get('side', 'right')
        dt_params, dx_params = parameters
        p_multipliers = (1.0 / (np.abs(self.elementwise_dtn(dt_params))
                                + np.abs(self.elementwise_dxn(dx_params, power=2))
                                + self.elementwise_dxn(dx_params, power=4))).ravel()

        # If including parameters, need an extra diagonal matrix to account for this (right-side preconditioning)
        if side == 'right':
            pexp = kwargs.get('pexp', (1, 1))
            return np.diag(np.concatenate((p_multipliers,
                                           self._parameter_preconditioning(dt_params, dx_params, pexp=pexp)), axis=0))
        else:
            return np.diag(p_multipliers)

    def _parameter_preconditioning(self, dt_params, dx_params):
        parameter_multipliers = []
        if not self.constraints['T']:
            parameter_multipliers.append(dt_params[0]**-1)
        if not self.constraints['L']:
            parameter_multipliers.append(dx_params[0]**-4)
        return np.array(parameter_multipliers)

    def nonlinear(self, other, **kwargs):
        """ nonlinear computation of the nonlinear term of the Kuramoto-Sivashinsky equation

        Parameters
        ----------

        other : OrbitKS
            The second component of the nonlinear product see Notes for details
        qk_matrix : matrix
            The matrix with the correctly ordered spatial frequencies.

        Notes
        -----
        The nonlinear product is the name given to the elementwise product equivalent to the
        convolution of spatiotemporal Fourier modes. It's faster and more accurate hence why it is used.
        The matrix vector product takes the form d_x (u * v), but the "normal" usage is d_x (u * u); in the latter
        case other is the same as self.

        """
        # Elementwise product, both self and other should be in physical field basis.
        assert (self.basis == 'field') and (other.basis == 'field')
        return 0.5 * self.statemul(other).dx(**kwargs)

    def rnonlinear(self, other, return_array=False):
        """ nonlinear computation of the nonlinear term of the adjoint Kuramoto-Sivashinsky equation

        Parameters
        ----------

        other : OrbitKS
            The second component of the nonlinear product see Notes for details
        qk_matrix : matrix
            The matrix with the correctly ordered spatial frequencies.

        Notes
        -----
        The nonlinear product is the name given to the elementwise product equivalent to the
        convolution of spatiotemporal Fourier modes. It's faster and more accurate hence why it is used.
        The matrix vector product takes the form -1 * u * d_x v.

        """
        assert self.basis == 'field'
        if return_array:
            # cannot return modes from derivative because it needs to be a class instance so IFFT can be applied.
            return -1.0 * self.statemul(other.dx().transform(to='field')).transform(to='modes').state
        else:
            return -1.0 * self.statemul(other.dx().transform(to='field')).transform(to='modes')

    def reflection(self):
        """ Reflect the velocity field about the spatial midpoint

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is the reflected velocity field -u(-x,t).
        """
        # Different points in space represented by columns of the state array
        reflected_field = -1.0*np.roll(np.fliplr(self.transform(to='field').state), 1, axis=1)
        return self.__class__(state=reflected_field, basis='field',
                              parameters=(self.T, self.L, -1.0*self.S)).transform(to=self.basis)

    def rescale(self, magnitude=3., inplace=False, method='absolute'):
        """ Scalar multiplication

        Parameters
        ----------
        num : float
            Scalar value to rescale by.

        Notes
        -----
        This rescales the physical field such that the absolute value of the max/min takes on a new value
        of num
        """

        if inplace:
            original_basis = self.basis
            field = self.transform(to='field', inplace=True).state
            if method == 'absolute':
                rescaled_field = ((magnitude * field) / np.max(np.abs(field.ravel())))
            elif method == 'power':
                rescaled_field = np.sign(field) * np.abs(field)**magnitude
            elif method is None:
                return self
            else:
                raise ValueError('Unrecognizable method.')
            self.state = rescaled_field
            return self.transform(to=original_basis, inplace=True)
        else:
            field = self.transform(to='field').state
            if method == 'absolute':
                rescaled_field = ((magnitude * field) / np.max(np.abs(field.ravel())))
            elif method == 'power':
                rescaled_field = np.sign(field) * np.abs(field)**magnitude
            elif method is None:
                return self
            else:
                raise ValueError('Unrecognizable method.')
            return self.__class__(state=rescaled_field, basis='field',
                                  parameters=self.parameters).transform(to=self.basis)

    def residual(self, apply_mapping=True):
        """ The value of the cost function

        Returns
        -------
        float :
            The value of the cost function, equal to 1/2 the squared L_2 norm of the spatiotemporal mapping,
            R = 1/2 ||F||^2.
        """
        if apply_mapping:
            v = self.transform(to='modes').spatiotemporal_mapping().state.ravel()
            return 0.5 * v.dot(v)
        else:
            u = self.state.ravel()
            return 0.5 * u.dot(u)

    def rotate(self, distance=0, axis=0, units='wavelength'):
        """ Rotate the velocity field in either space or time.

        Parameters
        ----------
        distance : float
            The rotation / translation amount, in dimensionless units of time or space.
        direction : str
            Takes values 'space' or 'time'. Direction which rotation will be performed in.
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS whose field has been rotated.

        Notes
        -----
        Due to periodic boundary conditions, translation is equivalent to rotation on a fundemantal level here.
        Hence the use of 'distance' instead of 'angle'. This can be negative. Also due to the periodic boundary
        conditions, a distance equaling the entire domain length is equivalent to no rotation. I.e.
        the rotation is always modulo L or modulo T.

        The orbit only remains a converged solution if rotations coincide with collocation
        points.  i.e. multiples of L / M and T / N. The reason for this is because arbitrary rotations require
        interpolation of the field.

        Rotation breaks discrete symmetry and destroys the solution. Users encouraged to change to OrbitKS first.

        """
        if axis == 0:
            thetak = distance*self._frequency_vector(self.dt_parameters)
            cosinek = np.cos(thetak)
            sinek = np.sin(thetak)

            orbit_to_rotate = self.transform(to='modes')
            # Refer to rotation matrix in 2-D for reference.
            cosine_block = np.tile(cosinek.reshape(-1, 1), (1, orbit_to_rotate.mode_shape[1]))
            sine_block = np.tile(sinek.reshape(-1, 1), (1, orbit_to_rotate.mode_shape[1]))

            modes_timereal = orbit_to_rotate.state[1:-orbit_to_rotate.n, :]
            modes_timeimaginary = orbit_to_rotate.state[-orbit_to_rotate.n:, :]
            # Elementwise product to account for matrix product with "2-D" rotation matrix
            rotated_real = (np.multiply(cosine_block, modes_timereal)
                            + np.multiply(sine_block, modes_timeimaginary))
            rotated_imag = (-np.multiply(sine_block, modes_timereal)
                            + np.multiply(cosine_block, modes_timeimaginary))
            time_rotated_modes = np.concatenate((orbit_to_rotate.state[0, :].reshape(1, -1),
                                                 rotated_real, rotated_imag), axis=0)
            return self.__class__(state=time_rotated_modes, basis='modes',
                                  parameters=self.parameters).transform(to=self.basis)
        else:
            if units == 'wavelength':
                distance = distance * 2*pi*np.sqrt(2)
            thetak = distance * self._wave_vector(self.dx_parameters)
            cosinek = np.cos(thetak)
            sinek = np.sin(thetak)

            orbit_to_rotate = self.transform(to='s_modes')
            # Refer to rotation matrix in 2-D for reference.
            cosine_block = np.tile(cosinek.reshape(1, -1), (orbit_to_rotate.N, 1))
            sine_block = np.tile(sinek.reshape(1, -1), (orbit_to_rotate.N, 1))

            # Rotation performed on spatial modes because otherwise rotation is ill-defined for Antisymmetric and
            # Shift-reflection symmetric Orbits.
            spatial_modes_real = orbit_to_rotate.state[:, :-orbit_to_rotate.m]
            spatial_modes_imaginary = orbit_to_rotate.state[:, -orbit_to_rotate.m:]
            rotated_real = (np.multiply(cosine_block, spatial_modes_real)
                            + np.multiply(sine_block, spatial_modes_imaginary))
            rotated_imag = (-np.multiply(sine_block, spatial_modes_real)
                            + np.multiply(cosine_block, spatial_modes_imaginary))
            rotated_s_modes = np.concatenate((rotated_real, rotated_imag), axis=1)

            return self.__class__(state=rotated_s_modes, basis='s_modes',
                                  parameters=self.parameters).transform(to=self.basis)

    def shift_reflection(self):
        """ Return a OrbitKS with shift-reflected velocity field

        Returns
        -------
        OrbitKS :
            OrbitKS with shift-reflected velocity field

        Notes
        -----
            Shift reflection in this case is a composition of spatial reflection and temporal translation by
            half of the period. Because these are in different dimensions these operations commute.
        """
        shift_reflected_field = np.roll(-1.0*np.roll(np.fliplr(self.state), 1, axis=1), self.N // 2, axis=0)
        return self.__class__(state=shift_reflected_field, basis='field',
                              parameters=self.parameters).transform(to=self.basis)

    def cell_shift(self, n_cell=2, axis=0):
        """ rotate half of a period in either axis.

        Parameters
        ----------
        axis

        Returns
        -------

        """
        return self.roll(self.field_shape[axis] // n_cell, axis=axis)

    def roll(self, shift, axis=0):
        field = self.transform(to='field').state
        return self.__class__(state=np.roll(field, shift, axis=axis), basis='field',
                              parameters=self.parameters).transform(to=self.basis)

    @property
    def shape(self):
        """ Convenience to not have to type '.state'

        Notes
        -----
        This is a property to not have to write '()' :)
        """
        return self.state.shape

    def spatiotemporal_mapping(self, **kwargs):
        """ The Kuramoto-Sivashinsky equation evaluated at the current state.

        kwargs :
        preconditioning : bool
        Apply custom preconditioner, only used in numerical methods.

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is the spatiotamporal fourier modes resulting from the calculation of the K-S equation:
            OrbitKS.state = u_t + u_xx + u_xxxx + 1/2 (u^2)_x
        :return:
        """
        # to be efficient, should be in modes basis.
        assert self.basis == 'modes', 'Convert to spatiotemporal Fourier mode basis before computing mapping func.'

        # # to avoid two IFFT calls, convert before nonlinear product
        orbit_field = self.transform(to='field')
        # 
        # # Compute the Kuramoto-sivashinsky equation
        mapping_modes = (self.dt(return_array=True) + self.dx(power=2, return_array=True)
                         + self.dx(power=4, return_array=True)
                         + orbit_field.nonlinear(orbit_field, return_array=True))
        return self.__class__(state=mapping_modes, basis='modes', parameters=self.parameters)

    def statemul(self, other):
        """ Elementwise multiplication of two Orbits states

        Returns
        -------
        OrbitKS :
            The OrbitKS representing the product.

        Notes
        -----
        Only really makes sense when taking an elementwise product between Orbits defined on spatiotemporal
        domains of the same size.
        """
        if isinstance(other, np.ndarray):
            product = np.multiply(self.state, other)
        else:
            product = np.multiply(self.state, other.state)
        return self.__class__(state=product, basis=self.basis, parameters=self.parameters)

    def _random_initial_condition(self, parameters, **kwargs):
        """ Initial a set of random spatiotemporal Fourier modes
        Parameters
        ----------
        T : float
            Time period
        L : float
            Space period
        **kwargs
            time_scale : int
                The number of temporal frequencies to keep after truncation.
            space_scale : int
                The number of spatial frequencies to get after truncation.
        Returns
        -------
        self :
            OrbitKS whose state has been modified to be a set of random Fourier modes.
        Notes
        -----
        These are the initial condition generators that I find the most useful. If a different method is
        desired, simply pass the array as 'state' variable to __init__.

        By initializing the shape parameters and orbit parameters, the other properties get initialized, so
        they can be referenced in what follows (self.dx_parameters, self.dt_parameters). I am unsure whether or not
        this is bad practice but they could be replaced by the corresponding tuples. The reason why this is avoided
        is so this function generalizes to subclasses.
        """

        spectrum = kwargs.get('spectrum', 'gaussian')
        tscale = kwargs.get('tscale', int(np.round(self.T / 25.)))
        xscale = kwargs.get('xscale', int(1 + np.round(self.L / (2*pi*np.sqrt(2)))))
        xvar = kwargs.get('xvar', np.sqrt(xscale))
        tvar = kwargs.get('tvar', np.sqrt(tscale))
        np.random.seed(kwargs.get('seed', None))

        # also accepts N and M as kwargs
        self.N, self.M = self.__class__.parameter_based_discretization(parameters, **kwargs)
        self.n, self.m = int(self.N // 2) - 1, int(self.M // 2) - 1

        # I think this is the easiest way to get symmetry-dependent Fourier mode arrays' shapes.
        # power = 2 b.c. odd powers not defined for spacetime modes for discrete symmetries.
        space_ = np.sqrt((self.L / (2*pi))**2 * np.abs(self.elementwise_dxn(self.dx_parameters,
                                                                            power=2))).astype(int)
        time_ = (self.T / (2*pi)) * np.abs(self.elementwise_dtn(self.dt_parameters))

        random_modes = np.random.randn(*self.mode_shape)
        # piece-wise constant + exponential
        # linear-component based. multiply by preconditioner?
        # random modes, no modulation.

        if spectrum == 'gaussian':
            # spacetime gaussian modulation
            gaussian_modulator = np.exp(-((space_ - xscale)**2/(2*xvar)) - ((time_ - tscale)**2 / (2*tvar)))
            modes = np.multiply(gaussian_modulator, random_modes)

        elif spectrum == 'gtes':
            gtime_espace_modulator = np.exp(-1.0 * (np.abs(space_- xscale) / xvar) - ((time_ - tscale)**2 / (2*tvar)))
            modes = np.multiply(gtime_espace_modulator, random_modes)

        elif spectrum == 'exponential':
            # exponential decrease away from selected spatial scale
            truncate_indices = np.where(time_ > tscale)
            untruncated_indices = np.where(time_ <= tscale)
            time_[truncate_indices] = 0
            time_[untruncated_indices] = 1.
            exp_modulator = np.exp(-1.0 * np.abs(space_- xscale) / xvar)
            exp_modulator = np.multiply(time_, exp_modulator)
            modes = np.multiply(exp_modulator, random_modes)

        elif spectrum == 'linear_exponential':
            # Modulate the spectrum using the spatial linear operator; equivalent to preconditioning.
            truncate_indices = np.where(time_ > tscale)
            untruncated_indices = np.where(time_ <= tscale)
            time_[truncate_indices] = 0
            time_[untruncated_indices] = 1.
            # so we get qk^2 - qk^4
            mollifier = -1.0*np.abs(((2*pi*xscale/self.L)**2-(2*pi*xscale/self.L)**4)
                                    - ((2*pi*space_ / self.L)**2+(2*pi*space_/self.L)**4))
            modulated_modes = np.multiply(np.exp(mollifier), random_modes)
            modes = np.multiply(time_, modulated_modes)

        elif spectrum == 'linear':
            # Modulate the spectrum using the spatial linear operator; equivalent to preconditioning.
            truncate_indices = np.where(time_ > tscale)
            untruncated_indices = np.where(time_ <= tscale)
            time_[truncate_indices] = 0
            time_[untruncated_indices] = 1.
            # so we get qk^2 - qk^4
            mollifier = np.abs(((2*pi*xscale/self.L)**2-(2*pi*xscale/self.L)**4))
            modulated_modes = np.divide(random_modes, np.exp(mollifier))
            modes = np.multiply(time_, modulated_modes)

        elif spectrum == 'time_truncated':
            # need to use conditional statements before modifying values, hence why these are stored
            truncate_indices = np.where(time_ > tscale)
            untruncated_indices = np.where(time_ <= tscale)
            time_[truncate_indices] = 0
            time_[untruncated_indices] = 1.
            # time_[time_ != 1.] = 0.
            modes = np.multiply(time_, random_modes)
        else:
            modes = random_modes

        self.state = modes
        self.basis = 'modes'
        return self.rescale(kwargs.get('magnitude', 3.5), inplace=True,
                            method=kwargs.get('rescale_method', 'absolute'))

    def _parse_state(self, state, basis, **kwargs):
        shp = state.shape
        self.state = state
        self.basis = basis
        if basis == 'modes':
            self.N, self.M = shp[0] + 1, shp[1] + 2
        elif basis == 'field':
            self.N, self.M = shp
        elif basis == 's_modes':
            self.N, self.M = shp[0], shp[1] + 2
        else:
            raise ValueError('basis is unrecognizable')

        self.n, self.m = int(self.N // 2) - 1, int(self.M // 2) - 1
        return self

    def _parse_parameters(self, parameters, **kwargs):
        """ Determine orbit parameters from either parameter dictionary or individually passed variables.


        Parameters
        ----------
        T
        L
        kwargs

        Returns
        -------

        Notes
        -----
        The 'shape' parameters will only ever be parsed from the actual construction or passing of an array via
        the 'state' keyword argument. This is a safety measure to avoid errors that might occur by passing
        shape parameters and state arrays that do not in fact match.

        """
        self.constraints = kwargs.get('constraints', {'T': False, 'L': False})
        T, L = parameters[:2]
        if T == 0. and kwargs.get('nonzero_parameters', False):
            if kwargs.get('seed', None) is not None:
                np.random.seed(kwargs.get('seed', None))
            self.T = (kwargs.get('T_min', 20.)
                      + (kwargs.get('T_max', 180.) - kwargs.get('T_min', 20.))*np.random.rand())
        else:
            self.T = float(T)

        if L == 0. and kwargs.get('nonzero_parameters', False):
            if kwargs.get('seed', None) is not None:
                np.random.seed(kwargs.get('seed', None)+1)
            self.L = (kwargs.get('L_min', 22.)
                      + (kwargs.get('L_max', 66.) - kwargs.get('L_min', 22.))*np.random.rand())
        else:
            self.L = float(L)

        # for the sake of uniformity of save format, technically 0 will be returned even if not defined because
        # of __getattr__ definition.
        self.S = 0.
        return None

    @classmethod
    @lru_cache(maxsize=16)
    def _wave_vector(cls, dx_parameters, power=1):
        """ Spatial frequency vector for the current state

        Returns
        -------
        ndarray :
            Array of spatial frequencies of shape (m, 1)
        """
        L, M, m = dx_parameters[:3]
        q_m = ((2 * pi * M / L) * np.fft.fftfreq(M)[1:m+1]).reshape(1, -1)
        return q_m**power

    @classmethod
    @lru_cache(maxsize=16)
    def _frequency_vector(cls, dt_parameters, power=1):
        """
        Returns
        -------
        ndarray
            Temporal frequency array of shape {n, 1}

        Notes
        -----
        Extra factor of '-1' because of how the state is ordered; see __init__ for
        more details.

        """
        T, N, n = dt_parameters[:3]
        w_n = (-1.0 * (2 * pi * N / T) * np.fft.fftfreq(N)[1:n+1]).reshape(-1, 1)
        return w_n**power

    def _jac_lin(self):
        """ The linear component of the Jacobian matrix of the Kuramoto-Sivashinsky equation"""
        return self._dt_matrix() + self._dx_matrix(power=2) + self._dx_matrix(power=4)

    def _jac_nonlin(self):
        """ The nonlinear component of the Jacobian matrix of the Kuramoto-Sivashinsky equation

        Returns
        -------
        nonlinear_dx : matrix
            Matrix which represents the nonlinear component of the Jacobian. The derivative of
            the nonlinear term, which is
            (D/DU) 1/2 d_x (u .* u) = (D/DU) 1/2 d_x F (diag(F^-1 u)^2)  = d_x F( diag(F^-1 u) F^-1).
            See
            Chu, K.T. A direct matrix method for computing analytical Jacobians of discretized nonlinear
            integro-differential equations. J. Comp. Phys. 2009
            for details.

        Notes
        -----
        The obvious way of computing this, represented above, is to multiply the linear operators
        corresponding to d_x F( diag(F^-1 u) F^-1). However, if we slightly rearrange things such that
        the spatial differential is taken on spatial modes, then this function generalizes to the subclasses
        with discrete symmetry.
        """

        _jac_nonlin_left = self._dx_matrix().dot(self._time_transform_matrix())
        _jac_nonlin_middle = self._space_transform_matrix().dot(np.diag(self.transform(to='field').state.ravel()))
        _jac_nonlin_right = self._inv_spacetime_transform_matrix()
        _jac_nonlin = _jac_nonlin_left.dot(_jac_nonlin_middle).dot(_jac_nonlin_right)
        return _jac_nonlin

    def _jacobian_parameter_derivatives_concat(self, jac_):
        """ Concatenate parameter partial derivatives to Jacobian matrix

        Parameters
        ----------
        jac_ : np.ndArray,
        (N-1) * (M-2) dimensional array resultant from taking the derivative of the spatioatemporal mapping
        with respect to Fourier modes.
        parameter_constraints : tuple
        Flags which indicate which parameters are constrained; if unconstrained then need to augment the Jacobian
        with partial derivatives with respect to unconstrained parameters.

        Returns
        -------
        Jacobian augmented with parameter partial derivatives as columns. Required to solve for changes to period,
        space period in optimization process. Makes the system rectangular; needs to be solved by least squares type
        methods.

        """
        # If period is not fixed, need to include dF/dT in jacobian matrix
        if not self.constraints['T']:
            time_period_derivative = (-1.0 / self.T)*self.dt(return_array=True).reshape(-1, 1)
            jac_ = np.concatenate((jac_, time_period_derivative), axis=1)

        # If spatial period is not fixed, need to include dF/dL in jacobian matrix
        if not self.constraints['L']:
            self_field = self.transform(to='field')
            spatial_period_derivative = ((-2.0 / self.L) * self.dx(power=2, return_array=True)
                                         + (-4.0 / self.L) * self.dx(power=4, return_array=True)
                                         + (-1.0 / self.L) * self_field.nonlinear(self_field, return_array=True))
            jac_ = np.concatenate((jac_, spatial_period_derivative.reshape(-1, 1)), axis=1)

        return jac_

    def _dx_matrix(self, power=1, **kwargs):
        """ The space derivative matrix operator for the current state.

        Parameters
        ----------
        power :int
            The order of the derivative.
        **kwargs :
            basis: str
            The basis the current state is in, can be 'modes', 's_modes'
            or 'field'. (spatiotemporal modes, spatial_modes, or velocity field, respectively).
        Returns
        ----------
        spacetime_dxn : matrix
            The operator whose matrix-vector product with spatiotemporal
            Fourier modes is equal to the time derivative. Used in
            the construction of the Jacobian operator.

        Notes
        -----
        Before the kronecker product, the matrix space_dxn is the operator which would correctly take the
        time derivative of a set of M-2 spatial modes (technically M/2-1 real + M/2-1 imaginary components).
        Because we have time as an extra dimension, we need a number of copies of
        space_dxn equal to the number of temporal frequencies. If in the spatial mode basis, this is the
        number of time points instead.
        """

        basis = kwargs.get('basis', self.basis)
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        space_dxn = np.kron(so2_generator(power=power), np.diag(self._wave_vector(self.dx_parameters,
                                                                                  power=power).ravel()))
        if basis == 's_modes':
            # else use time discretization size.
            spacetime_dxn = np.kron(np.eye(self.N), space_dxn)
        else:
            # if spacetime modes, use the corresponding mode shape parameters
            spacetime_dxn = np.kron(np.eye(self.mode_shape[0]), space_dxn)

        return spacetime_dxn

    def _dt_matrix(self, power=1):
        """ The time derivative matrix operator for the current state.

        Parameters
        ----------
        power :int
            The order of the derivative.

        Returns
        ----------
        wk_matrix : matrix
            The operator whose matrix-vector product with spatiotemporal
            Fourier modes is equal to the time derivative. Used in
            the construction of the Jacobian operator.

        Notes
        -----
        Before the kronecker product, the matrix dt_n_matrix is the operator which would correctly take the
        time derivative of a single set of N-1 temporal modes. Because we have space as an extra dimension,
        we need a number of copies of dt_n_matrix equal to the number of spatial frequencies.
        """
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        dt_n_matrix = np.kron(so2_generator(power=power), np.diag(self._frequency_vector(self.dt_parameters,
                                                                                         power=power).ravel()))
        # Zeroth frequency was not included in frequency vector.
        dt_n_matrix = block_diag([[0]], dt_n_matrix)
        # Take kronecker product to account for the number of spatial modes.
        spacetime_dtn = np.kron(dt_n_matrix, np.eye(self.mode_shape[1]))
        return spacetime_dtn

    def _inv_spacetime_transform_matrix(self):
        """ Inverse Space-time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatiotemporal modes into a physical field u(x,t)

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        return np.dot(self._inv_space_transform_matrix(), self._inv_time_transform_matrix())

    def _spacetime_transform_matrix(self):
        """ Space-time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a physical field u(x,t) into a set of spatiotemporal modes.

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        return np.dot(self._time_transform_matrix(), self._space_transform_matrix())

    def _time_transform(self, inplace=False):
        """ Temporal Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        modes = rfft(self.state, norm='ortho', axis=0)
        modes_real = modes.real[:-1, :]
        modes_imag = modes.imag[1:-1, :]
        spacetime_modes = np.concatenate((modes_real, modes_imag), axis=0)
        spacetime_modes[1:, :] = np.sqrt(2) * spacetime_modes[1:, :]
        if inplace:
            self.basis = 'modes'
            self.state = spacetime_modes
            return self
        else:
            return self.__class__(state=spacetime_modes, basis='modes', parameters=self.parameters)

    def _inv_time_transform(self, inplace=False):
        """ Temporal Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the temporal Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.

        modes = self.state
        time_real = modes[:-self.n, :]
        time_imaginary = np.concatenate((np.zeros([1, self.mode_shape[1]]), modes[-self.n:, :]), axis=0)
        complex_modes = np.concatenate((time_real + 1j * time_imaginary, np.zeros([1, self.mode_shape[1]])), axis=0)
        complex_modes[1:, :] = (1./np.sqrt(2)) * complex_modes[1:, :]
        space_modes = irfft(complex_modes, norm='ortho', axis=0)
        if inplace:
            self.basis = 's_modes'
            self.state = space_modes
            return self
        else:
            return self.__class__(state=space_modes, basis='s_modes', parameters=self.parameters)

    def _space_transform(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        space_modes_complex = np.sqrt(2) * rfft(self.state, norm='ortho', axis=1)[:, 1:-1]
        spatial_modes = np.concatenate((space_modes_complex.real, space_modes_complex.imag), axis=1)
        if inplace:
            self.basis = 's_modes'
            self.state = spatial_modes
            return self
        else:
            return self.__class__(state=spatial_modes, basis='s_modes', parameters=self.parameters)

    def _inv_space_transform(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Make the modes complex valued again.
        complex_modes = self.state[:, :-self.m] + 1j * self.state[:, -self.m:]
        # Re-add the zeroth and Nyquist spatial frequency modes (zeros) and then transform back
        z = np.zeros([self.N, 1])
        field = (1./np.sqrt(2))*irfft(np.concatenate((z, complex_modes, z), axis=1), norm='ortho', axis=1)
        if inplace:
            self.basis = 'field'
            self.state = field
            return self
        else:
            return self.__class__(state=field, basis='field', parameters=self.parameters)

    def _time_transform_matrix(self):
        """ Inverse Time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatiotemporal modes into a set of spatial modes

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        dft_mat = rfft(np.eye(self.N), norm='ortho', axis=0)
        time_dft_mat = np.concatenate((dft_mat[:-1, :].real,
                                       dft_mat[1:-1, :].imag), axis=0)
        time_dft_mat[1:, :] = np.sqrt(2)*time_dft_mat[1:, :]
        return np.kron(time_dft_mat, np.eye(self.M-2))

    def _inv_time_transform_matrix(self):
        """ Time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatial modes into a set of spatiotemporal modes.

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        idft_mat_real = irfft(np.eye(self.N//2 + 1), norm='ortho', axis=0)
        idft_mat_imag = irfft(1j * np.eye(self.N//2 + 1), norm='ortho', axis=0)
        time_idft_mat = np.concatenate((idft_mat_real[:, :-1],
                                        idft_mat_imag[:, 1:-1]), axis=1)
        # to make the transformations orthogonal, based on scipy implementation of scipy.fft.irfft
        time_idft_mat[:, 1:] = time_idft_mat[:, 1:]/np.sqrt(2)
        return np.kron(time_idft_mat, np.eye(self.M-2))

    def _inv_space_transform_matrix(self):
        """ Inverse spatial Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatial Fourier modes into a physical field u(x,t).

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the inverse Fourier transform.
        """

        idft_mat_real = irfft(np.eye(self.M//2 + 1), norm='ortho', axis=0)[:, 1:-1]
        idft_mat_imag = irfft(1j*np.eye(self.M//2 + 1), norm='ortho', axis=0)[:, 1:-1]
        # to make the transformations orthogonal, based on scipy implementation of scipy.fft.irfft
        space_idft_mat = (1./np.sqrt(2)) * np.concatenate((idft_mat_real, idft_mat_imag), axis=1)
        return np.kron(np.eye(self.N), space_idft_mat)

    def _space_transform_matrix(self):
        """ Spatial Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a physical field u(x,t) into a set of spatial Fourier modes.

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        The matrix is formatted such that is u(x,t), the entire spatiotemporal discretization of the
        orbit is vector resulting from flattening the 2-d array wherein increasing column index is increasing space
        variable x and increasing rows is *decreasing* time. This is because of the Physics convention for increasing
        time to always be "up". By taking the real and imaginary components of the DFT matrix and concatenating them
        we convert the output from a vector with elements form u_k(t) = a_k + 1j*b_k(t) to a vector of the form
        [a_0, a_1, a_2, ..., b_1, b_2, b_3, ...]. The kronecker product enables us to act on the entire orbit
        at once instead of a single instant in time.

        Discard zeroth mode because of the constraint on Galilean velocity (mean flow). Discard Nyquist frequency
        because of real input of even dimension; just makes matrix operators awkward as well.
        """

        dft_mat = rfft(np.eye(self.M), norm='ortho', axis=0)[1:-1, :]
        space_dft_mat = np.sqrt(2) * np.concatenate((dft_mat.real, dft_mat.imag), axis=0)
        return np.kron(np.eye(self.N), space_dft_mat)

    def _inv_spacetime_transform(self, inplace=False):
        """ Inverse space-time Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS instance in the physical field basis.
        """
        if inplace:
            self._inv_time_transform(inplace=True)._inv_space_transform(inplace=True)
            return self
        else:
            return self._inv_time_transform()._inv_space_transform()

    def _spacetime_transform(self, inplace=False):
        """ Space-time Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS instance in the spatiotemporal mode basis.
        """
        if inplace:
            self._space_transform(inplace=True)._time_transform(inplace=True)
            return self
        else:
            # Return transform of field
            return self._space_transform()._time_transform()


class RelativeOrbitKS(OrbitKS):

    def __init__(self, state=None, basis='modes', parameters=(0., 0., 0.), frame='comoving', **kwargs):
        # For uniform save format
        super().__init__(state=state, basis=basis, parameters=parameters, frame=frame, **kwargs)
        # If the frame is comoving then the calculated shift will always be 0 by definition of comoving frame.
        # The cases where is makes sense to calculate the shift
        # if self.S == 0. and (self.frame == 'physical' or kwargs.get('nonzero_parameters', False) or state is None):
        #     self.S = calculate_spatial_shift(self.transform(to='s_modes').state, self.L)

        # If specified that the state is in physical frame then shift is calculated.
        if self.S == 0. and (frame == 'physical' or kwargs.get('nonzero_parameters', True)):
            self.S = calculate_spatial_shift(self.transform(to='s_modes').state, self.L, **kwargs)

    def copy(self):
        return self.__class__(state=self.state.copy(), basis=self.basis, parameters=self.parameters, frame=self.frame)

    def comoving_mapping_component(self, return_array=False):
        """ Co-moving frame component of spatiotemporal mapping """
        return (-self.S / self.T)*self.dx(return_array=return_array)

    def comoving_matrix(self):
        """ Operator that constitutes the co-moving frame term """
        return (-self.S / self.T)*self._dx_matrix()

    def convert(self, inplace=False, to='modes'):
        """ Convert current state to a different basis.
        This instance method is just a wrapper for different
        Fourier transforms. It's purpose is to remove the
        need for the user to keep track of the basis by hand.
        This should be used as opposed to Fourier transforms.
        Parameters
        ----------
        inplace : bool
            Whether or not to perform the conversion "in place" or not.
        to : str
            One of the following: 'field', 's_modes', 'modes'. Specifies
            the basis which the orbit will be converted to. \
        Raises
        ----------
        ValueError
            Raised if the provided basis is unrecognizable.
        Returns
        ----------
        converted_orbit : orbit or orbit subclass instance
            The class instance in the new basis.
        """
        orbit_in_specified_basis = super().transform(inplace=inplace, to=to)
        orbit_in_specified_basis.frame = self.frame
        return orbit_in_specified_basis

    def change_reference_frame(self, to='comoving'):
        """ Transform to (or from) the co-moving frame depending on the current reference frame

        Parameters
        ----------
        inplace : bool
            Whether to perform in-place or not

        Returns
        -------
        RelativeOrbitKS :
            RelativeOrbitKS in transformed reference frame.

        Notes
        -----
        This operation occurs in spatial Fourier mode basis because I feel its more straightforward to understand
        a time parameterized shift of spatial modes; this is the consistent approach given how the shifts are
        calculated.

        Spatiotemporal modes are not designed to be used in the physical reference frame due to Gibbs' phenomenon
        due to discontinuity. Physical reference frame should really only be used to plot the relative periodic field.
        """
        # shift is ALWAYS stored as the shift amount from comoving to physical frame.
        if to == 'comoving':
            if self.frame == 'physical':
                shift = -1.0 * self.S
            else:
                return self
        elif to == 'physical':
            if self.frame == 'comoving':
                shift = self.S
            else:
                return self
        else:
            raise ValueError('Trying to change to unrecognizable reference frame.')

        s_modes = self.transform(to='s_modes').state
        time_vector = np.flipud(np.linspace(0, self.T, num=self.N, endpoint=True)).reshape(-1, 1)
        translation_per_period = shift / self.T
        time_dependent_translations = translation_per_period*time_vector
        thetak = time_dependent_translations.reshape(-1, 1)*self._wave_vector(self.dx_parameters).ravel()
        cosine_block = np.cos(thetak)
        sine_block = np.sin(thetak)
        real_modes = s_modes[:, :-self.m]
        imag_modes = s_modes[:, -self.m:]
        frame_rotated_s_modes_real = (np.multiply(real_modes, cosine_block)
                                      + np.multiply(imag_modes, sine_block))
        frame_rotated_s_modes_imag = (-np.multiply(real_modes, sine_block)
                                      + np.multiply(imag_modes, cosine_block))
        frame_rotated_s_modes = np.concatenate((frame_rotated_s_modes_real, frame_rotated_s_modes_imag), axis=1)

        rotated_orbit = self.__class__(state=frame_rotated_s_modes, basis='s_modes',
                                       parameters=(self.T, self.L, self.S), frame=to)
        return rotated_orbit.transform(to=self.basis, inplace=True)

    def dt(self, power=1, return_array=False):
        """ A time derivative of the current state.

        Parameters
        ----------
        power :int
            The order of the derivative.

        Returns
        ----------
        orbit_dtn : OrbitKS or subclass instance
            The class instance whose state is the time derivative in
            the spatiotemporal mode basis.
        """
        if self.frame == 'comoving':
            return super().dt(power=power, return_array=return_array)
        else:
            raise ValueError(
                'Attempting to compute time derivative of '+str(self)+'in physical reference frame.')

    def from_fundamental_domain(self):
        return self.change_reference_frame(to='comoving')

    def from_numpy_array(self, state_array, **kwargs):
        """ Utility to convert from numpy array to orbithunter format for scipy wrappers.
        :param orbit:
        :param state_array:
        :param parameter_constraints:
        :return:

        Notes
        -----
        Written as a general method that covers all subclasses instead of writing individual methods.
        """

        mode_shape, mode_size = self.mode_shape, self.state.size
        modes = state_array.ravel()[:mode_size]
        # We slice off the modes and the rest of the list pertains to parameters; note if the state_array had
        # parameters, and parameters were added by

        params_list = list(kwargs.pop('parameters', state_array.ravel()[mode_size:].tolist()))
        parameters = tuple(params_list.pop(0) if not p and params_list else 0 for p in self.constraints.values())
        return self.__class__(state=np.reshape(modes, mode_shape), basis='modes',
                              parameters=parameters, **kwargs)

    def _jacobian_parameter_derivatives_concat(self, jac_):
        """ Concatenate parameter partial derivatives to Jacobian matrix

        Parameters
        ----------
        jac_ : np.ndArray,
        (N-1) * (M-2) dimensional array resultant from taking the derivative of the spatioatemporal mapping
        with respect to Fourier modes.
        parameter_constraints : tuple
        Flags which indicate which parameters are constrained; if unconstrained then need to augment the Jacobian
        with partial derivatives with respect to unconstrained parameters.

        Returns
        -------
        Jacobian augmented with parameter partial derivatives as columns. Required to solve for changes to period,
        space period in optimization process. Makes the system rectangular; needs to be solved by least squares type
        methods.

        """
        # If period is not fixed, need to include dF/dT in jacobian matrix
        if not self.constraints['T']:
            time_period_derivative = (-1.0 / self.T)*(self.dt(return_array=True)
                                                      + (-self.S / self.T)*self.dx(return_array=True)
                                                      ).reshape(-1, 1)
            jac_ = np.concatenate((jac_, time_period_derivative), axis=1)

        # If spatial period is not fixed, need to include dF/dL in jacobian matrix
        if not self.constraints['L']:
            self_field = self.transform(to='field')
            spatial_period_derivative = ((-2.0 / self.L) * self.dx(power=2, return_array=True)
                                         + (-4.0 / self.L) * self.dx(power=4, return_array=True)
                                         + (-1.0 / self.L) * self_field.nonlinear(self_field, return_array=True))
            jac_ = np.concatenate((jac_, spatial_period_derivative.reshape(-1, 1)), axis=1)

        if not self.constraints['S']:
            spatial_shift_derivatives = (-1.0 / self.T)*self.dx(return_array=True)
            jac_ = np.concatenate((jac_, spatial_shift_derivatives.reshape(-1, 1)), axis=1)

        return jac_

    def _jac_lin(self):
        """ Extension of the OrbitKS method that includes the term for spatial translation symmetry"""
        return super()._jac_lin() + self.comoving_matrix()

    def matvec(self, other, **kwargs):
        """ Extension of parent class method

        Parameters
        ----------
        other : RelativeOrbitKS
            RelativeOrbitKS instance whose state represents the vector in the matrix-vector multiplication.
        parameter_constraints : tuple
            Determines whether to include period and spatial period
            as variables.
        preconditioning : bool
            Whether or not to apply (left) preconditioning P (Ax)

        Returns
        -------
        RelativeOrbitKS
            RelativeOrbitKS whose state and other parameters result from the matrix-vector product.

        Notes
        -----
        Equivalent to computation of (v_t + v_xx + v_xxxx + phi * v_x) + d_x (u .* v)
        The additional term phi * v_x is in the linear portion of the equation, meaning that
        we can calculate it and add it to the rest of the mapping a posteriori.
        """

        assert (self.basis == 'modes') and (other.basis == 'modes')
        matvec_orbit = super().matvec(other)
        matvec_comoving = self.__class__(state=other.state, parameters=self.parameters).comoving_mapping_component()
        # this is needed unless all parameters are fixed, but that isn't ever a realistic choice.
        self_dx = self.dx(return_array=True)
        if not self.constraints['T']:
            matvec_comoving.state += other.T * (-1.0 / self.T) * (-self.S / self.T) * self_dx

        if not self.constraints['L']:
            # Derivative of mapping with respect to T is the same as -1/T * u_t
            matvec_comoving.state += other.L * (-1.0 / self.L) * (-self.S / self.T) * self_dx

        if not self.constraints['S']:
            # technically could do self_comoving / self.S but this can be numerically unstable when self.S is small
            matvec_comoving.state += other.S * (-1.0 / self.T) * self_dx

        return matvec_orbit + matvec_comoving

    def _pad(self, size, axis=0):
        """ Increase the size of the discretization via zero-padding

        Parameters
        ----------
        size : int
            The new size of the discretization, must be an even integer
            larger than the current size of the discretization.
        dimension : str
            Takes values 'space' or 'time'. The dimension that will be padded.

        Returns
        -------
        OrbitKS :
            OrbitKS instance with larger discretization.

        Notes
        -----
        Need to account for the normalization factors by multiplying by old, dividing by new.

        """
        assert self.frame == 'comoving', 'Mode padding requires comoving frame; set padding=False if plotting'
        return super()._pad(size, axis=axis)

    def _truncate(self, size, axis=0):
        """ Decrease the size of the discretization via truncation

        Parameters
        -----------
        size : int
            The new size of the discretization, must be an even integer
            smaller than the current size of the discretization.
        dimension : str
            Takes values 'space' or 'time'. The dimension that will be truncated.

        Returns
        -------
        OrbitKS
            OrbitKS instance with larger discretization.
        """
        assert self.frame == 'comoving', 'Mode truncation requires comoving frame; set padding=False if plotting'
        return super()._truncate(size, axis=axis)

    @property
    def dt_parameters(self):
        return self.T, self.N, self.n, self.M-2

    @property
    def parameters(self):
        return self.T, self.L, self.S

    @property
    def mode_shape(self):
        return max([self.N-1, 1]), self.M-2

    @property
    def dimensions(self):
        return self.T, self.L

    def _parameter_preconditioning(self, dt_params, dx_params):
        parameter_multipliers = []
        if not self.constraints['T']:
            parameter_multipliers.append(dt_params[0]**-1)
        if not self.constraints['L']:
            parameter_multipliers.append(dx_params[0]**-4)
        if not self.constraints['S']:
            parameter_multipliers.append(1)
        return np.array(parameter_multipliers)

    def _parse_parameters(self, parameters, **kwargs):
        T, L, S = parameters[:3]

        self.constraints = kwargs.get('constraints', {'T': False, 'L': False, 'S': False})
        self.frame = kwargs.get('frame', 'comoving')

        if T == 0. and kwargs.get('nonzero_parameters', False):
            if kwargs.get('seed', None) is not None:
                np.random.seed(kwargs.get('seed', None))
            self.T = (kwargs.get('T_min', 20.)
                      + (kwargs.get('T_max', 180.) - kwargs.get('T_min', 20.))*np.random.rand())
        else:
            self.T = float(T)

        if L == 0. and kwargs.get('nonzero_parameters', False):
            if kwargs.get('seed', None) is not None:
                np.random.seed(kwargs.get('seed', None)+1)
            self.L = (kwargs.get('L_min', 22.)
                      + (kwargs.get('L_max', 66.) - kwargs.get('L_min', 22.))*np.random.rand())
        else:
            self.L = float(L)
        # Would like to calculate shift here but we need a state to be initialized first, so this is handled
        # after the super().__init__ call for relative periodic solutions.
        self.S = S
        return None

    def rmatvec(self, other, **kwargs):
        """ Extension of the parent method to RelativeOrbitKS

        Notes
        -----
        Computes all of the extra terms due to inclusion of comoving mapping component, stores them in
        a class instance and then increments the original rmatvec state, T, L, S with its values.

        """
        # For specific computation of the linear component instead
        # of arbitrary derivatives we can optimize the calculation by being specific.
        return super().rmatvec(other, **kwargs) - 1.0 * other.comoving_mapping_component()

    def rmatvec_parameters(self, self_field, other):
        other_modes = other.state.ravel()
        self_dx_modes = self.dx(return_array=True)

        if not self.constraints['T']:
            # Derivative with respect to T term equal to DF/DT * v
            rmatvec_T = (-1.0 / self.T) * (self.dt(return_array=True)
                                          + (-self.S / self.T) * self_dx_modes).ravel().dot(other_modes)
        else:
            rmatvec_T = 0

        if not self.constraints['L']:
            # change in L, dL, equal to DF/DL * v
            rmatvec_L = ((-2.0 / self.L) * self.dx(power=2, return_array=True)
                         + (-4.0 / self.L) * self.dx(power=4, return_array=True)
                         + (-1.0 / self.L) * (self_field.nonlinear(self_field, return_array=True)
                                              + (-self.S / self.T) * self_dx_modes)
                        ).ravel().dot(other_modes)

        else:
            rmatvec_L = 0

        if not self.constraints['S']:
            rmatvec_S = (-1.0 / self.T) * self_dx_modes.ravel().dot(other_modes)
        else:
            rmatvec_S = 0.

        return rmatvec_T, rmatvec_L, rmatvec_S

    def spatiotemporal_mapping(self, **kwargs):
        """ Extension of OrbitKS method to include co-moving frame term. """
        return super().spatiotemporal_mapping() + self.comoving_mapping_component()

    def state_vector(self):
        """ Vector which completely describes the orbit."""
        return np.concatenate((self.state.reshape(-1, 1),
                               np.array([[float(self.T)]]),
                               np.array([[float(self.L)]]),
                               np.array([[float(self.S)]])), axis=0)

    def verify_integrity(self):
        """ Check whether the orbit converged to an equilibrium or close-to-zero solution """
        orbit_with_inverted_shift = self.copy()
        orbit_with_inverted_shift.S = -self.S
        residual_imported_S = self.residual()
        residual_negated_S = orbit_with_inverted_shift.residual()
        if residual_imported_S > residual_negated_S:
            orbit_ = orbit_with_inverted_shift
        else:
            orbit_ = self.copy()
        # Take the L_2 norm of the field, if uniformly close to zero, the magnitude will be very small.
        field_orbit = orbit_.transform(to='field')

        # See if the L_2 norm is beneath a threshold value, if so, replace with zeros.
        if field_orbit.norm() < 10**-5 or self.T in [0, 0.]:
            code = 4
            return RelativeEquilibriumOrbitKS(state=np.zeros([self.N, self.M]), basis='field',
                                              parameters=self.parameters).transform(to=self.basis), code
        # Equilibrium is defined by having no temporal variation, i.e. time derivative is a uniformly zero.
        elif self.T in [0., 0]:
            # If there is sufficient evidence that solution is an equilibrium, change its class
            code = 3
            # store T just in case we want to refer to what the period was before conversion to EquilibriumOrbitKS
            return EquilibriumOrbitKS(state=field_orbit.state, basis='field',
                                      parameters=self.parameters).transform(to=self.basis), code
        elif  field_orbit.dt().transform(to='field').norm() < 10**-5:
            # If there is sufficient evidence that solution is an equilibrium, change its class
            code = 3
            return RelativeEquilibriumOrbitKS(state=self.transform(to='modes').state, basis='modes',
                                              parameters=self.parameters).transform(to=self.basis), code
        else:
            code = 1
            return orbit_, code

    def to_fundamental_domain(self):
        return self.change_reference_frame(to='physical')


class AntisymmetricOrbitKS(OrbitKS):

    def __init__(self, state=None, basis='modes', parameters=(0., 0., 0.), **kwargs):
        super().__init__(state=state, basis=basis, parameters=parameters, **kwargs)

    def dx(self, power=1, return_array=False):
        """ Overwrite of parent method """
        if np.mod(power, 2):
            dxn_s_modes = swap_modes(np.multiply(self.elementwise_dxn(self.dx_parameters, power=power),
                                                 self.transform(to='s_modes').state), axis=1)
            # Typically have to keep odd ordered spatial derivatives as spatial modes or field.
            if return_array:
                return dxn_s_modes
            else:
                return self.__class__(state=dxn_s_modes, basis='s_modes', parameters=self.parameters)
        else:
            dxn_modes = np.multiply(self.elementwise_dxn(self.dx_parameters, power=power),
                                    self.transform(to='modes').state)
            if return_array:
                return dxn_modes
            else:
                return self.__class__(state=dxn_modes, basis='modes',
                                      parameters=self.parameters).transform(to=self.basis)

    @classmethod
    @lru_cache(maxsize=16)
    def elementwise_dxn(cls, dx_parameters, power=1):
        """ Matrix of temporal mode frequencies

        Creates and returns a matrix whose elements
        are the properly ordered spatial frequencies,
        which is the same shape as the spatiotemporal
        Fourier mode state. The elementwise product
        with a set of spatiotemporal Fourier modes
        is equivalent to taking a spatial derivative.

        Returns
        ----------
        matrix
            Matrix of spatial frequencies
        """
        q = cls._wave_vector(dx_parameters, power=power)
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        c1, c2 = so2_coefficients(power=power)
        # Create elementwise spatial frequency matrix
        if np.mod(power, 2):
            # If the order of the derivative is odd, need to apply to spatial modes not spacetime modes.
            dxn_multipliers = np.tile(np.concatenate((c1*q, c2*q), axis=1), (dx_parameters[-2], 1))
        else:
            # if order is even, make the frequencies into an array with same shape as modes; c1 = c2 when power is even.
            dxn_multipliers = np.tile(c1*q, (dx_parameters[-1], 1))
        return dxn_multipliers

    def _dx_matrix(self, power=1, **kwargs):
        """ Overwrite of parent method """
        basis = kwargs.get('basis', self.basis)
        # Define spatial wavenumber vector
        if basis == 'modes':
            _, c = so2_coefficients(power=power)
            dx_n_matrix = c * np.diag(self._wave_vector(self.dx_parameters, power=power).ravel())
            _dx_matrix_complete = np.kron(np.eye(self.mode_shape[0]), dx_n_matrix)
        else:
            dx_n_matrix = np.kron(so2_generator(power=power), np.diag(self._wave_vector(self.dx_parameters,
                                                                                        power=power).ravel()))
            _dx_matrix_complete = np.kron(np.eye(self.N), dx_n_matrix)
        return _dx_matrix_complete

    def _jac_nonlin(self):
        """ The nonlinear component of the Jacobian matrix of the Kuramoto-Sivashinsky equation

        Returns
        -------
        nonlinear_dx : matrix
            Matrix which represents the nonlinear component of the Jacobian. The derivative of
            the nonlinear term, which is
            (D/DU) 1/2 d_x (u .* u) = (D/DU) 1/2 d_x F (diag(F^-1 u)^2)  = d_x F( diag(F^-1 u) F^-1).
            See
            Chu, K.T. A direct matrix method for computing analytical Jacobians of discretized nonlinear
            integro-differential equations. J. Comp. Phys. 2009
            for details.

        Notes
        -----
        The obvious way of computing this, represented above, is to multiply the linear operators
        corresponding to d_x F( diag(F^-1 u) F^-1). However, if we slightly rearrange things such that
        the spatial differential is taken on spatial modes, then this function generalizes to the subclasses
        with discrete symmetry.
        """

        _jac_nonlin_left = self._time_transform_matrix().dot(self._dx_matrix(basis='s_modes'))
        _jac_nonlin_middle = self._space_transform_matrix().dot(np.diag(self.transform(to='field').state.ravel()))
        _jac_nonlin_right = self._inv_spacetime_transform_matrix()
        _jac_nonlin = _jac_nonlin_left.dot(_jac_nonlin_middle).dot(_jac_nonlin_right)

        return _jac_nonlin

    def from_fundamental_domain(self, inplace=False, **kwargs):
        """ Overwrite of parent method """
        return self.__class__(state=np.concatenate((self.reflection().state, self.state), axis=1),
                              basis='field', parameters=(self.T, 2*self.L, 0.))

    def _pad(self, size, axis=0):
        """ Overwrite of parent method """
        modes = self.transform(to='modes')
        if np.mod(size, 2):
            raise ValueError('New discretization size must be an even number, preferably a power of 2')
        else:
            if axis == 0:
                # Split into real and imaginary components, pad separately.
                first_half = modes.state[:-modes.n, :]
                second_half = modes.state[-modes.n:, :]
                padding_number = int((size-modes.N) // 2)
                padding = np.zeros([padding_number, modes.state.shape[1]])
                padded_modes = np.sqrt(size / modes.N) * np.concatenate((first_half, padding, second_half, padding), axis=0)
            else:
                padding_number = int((size-modes.M) // 2)
                padding = np.zeros([modes.state.shape[0], padding_number])
                padded_modes = np.sqrt(size / modes.M) * np.concatenate((modes.state, padding), axis=1)
        return self.__class__(state=padded_modes, basis='modes',
                              parameters=self.parameters).transform(to=self.basis)

    def _truncate(self, size, axis=0):
        """ Overwrite of parent method """
        modes = self.transform(to='modes')
        if np.mod(size, 2):
            raise ValueError('New discretization size must be an even number, preferably a power of 2')
        else:
            if axis == 0:
                truncate_number = int(size // 2) - 1
                first_half = modes.state[:truncate_number+1, :]
                second_half = modes.state[-modes.n:-modes.n+truncate_number, :]
                truncated_modes = np.sqrt(size / modes.N) * np.concatenate((first_half, second_half), axis=0)
            else:
                truncate_number = int(size // 2) - 1
                truncated_modes = np.sqrt(size / modes.M) * modes.state[:, :truncate_number]
        return self.__class__(state=truncated_modes, basis='modes',
                              parameters=self.parameters).transform(to=self.basis)

    def nonlinear(self, other, return_array=False):
        """ nonlinear computation of the nonlinear term of the Kuramoto-Sivashinsky equation

        """
        # Elementwise product, both self and other should be in physical field basis.
        assert (self.basis == 'field') and (other.basis == 'field')
        # to get around the special behavior of discrete symmetries, will return spatial modes without this workaround.
        if return_array:
            return 0.5 * self.statemul(other).dx(return_array=False).transform(to='modes').state
        else:
            return 0.5 * self.statemul(other).dx(return_array=False).transform(to='modes')

    @property
    def dt_parameters(self):
        return self.T, self.N, self.n, self.m

    @property
    def dx_parameters(self):
        return self.L, self.M, self.m, self.N, max([self.N-1, 1])

    @property
    def mode_shape(self):
        return max([self.N-1, 1]), self.m

    @property
    def dimensions(self):
        return self.T, self.L

    def _parse_state(self, state, basis, **kwargs):
        shp = state.shape
        self.state = state
        self.basis = basis
        if basis == 'modes':
            self.N, self.M = shp[0] + 1, 2*shp[1] + 2
        elif basis == 'field':
            self.N, self.M = shp
        elif basis == 's_modes':
            self.N, self.M = shp[0], shp[1]+2
        else:
            raise ValueError('basis is unrecognizable')
        self.n, self.m = max([int(self.N // 2) - 1, 1]), int(self.M // 2) - 1
        return self

    def _time_transform_matrix(self):
        """ Inverse Time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatiotemporal modes into a set of spatial modes

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        dft_mat = rfft(np.eye(self.N), norm='ortho', axis=0)
        time_dft_mat = np.concatenate((dft_mat[:-1, :].real,
                                       dft_mat[1:-1, :].imag), axis=0)
        time_dft_mat[1:, :] = np.sqrt(2)*time_dft_mat[1:, :]
        # Note that if np.insert is given a 2-d array it will insert 1-d arrays corresponding to the axis argument.
        # in other words, this is inserting columns of zeros.
        ab_time_dft_mat = np.insert(time_dft_mat,
                                    np.arange(time_dft_mat.shape[1]),
                                    np.zeros([time_dft_mat.shape[0], time_dft_mat.shape[1]]),
                                    axis=1)

        return np.kron(ab_time_dft_mat, np.eye(self.m))

    def _inv_time_transform_matrix(self):
        """ Time Fourier transform operator

        Returns
        -------
        matrix :
            Matrix operator whose action maps a set of spatial modes into a set of spatiotemporal modes.

        Notes
        -----
        Only used for the construction of the Jacobian matrix. Do not use this for the Fourier transform.
        """
        idft_mat_real = irfft(np.eye(self.N//2 + 1), norm='ortho', axis=0)
        idft_mat_imag = irfft(1j*np.eye(self.N//2 + 1), norm='ortho', axis=0)
        time_idft_mat = np.concatenate((idft_mat_real[:, :-1],
                                        idft_mat_imag[:, 1:-1]), axis=1)
        time_idft_mat[:, 1:] = time_idft_mat[:, 1:]/np.sqrt(2)
        ab_time_idft_mat = np.insert(time_idft_mat,
                                     np.arange(time_idft_mat.shape[0]),
                                     np.zeros([time_idft_mat.shape[0], time_idft_mat.shape[1]]),
                                     axis=0)
        return np.kron(ab_time_idft_mat, np.eye(self.m))

    def _time_transform(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        modes = rfft(self.state, norm='ortho', axis=0)
        modes_real = modes.real[:-1, -self.m:]
        modes_imag = modes.imag[1:-1, -self.m:]
        spacetime_modes = np.concatenate((modes_real, modes_imag), axis=0)
        spacetime_modes[1:, :] = np.sqrt(2)*spacetime_modes[1:, :]
        if inplace:
            self.state = spacetime_modes
            self.basis = 'modes'
            return self
        else:
            return self.__class__(state=spacetime_modes, basis='modes', parameters=self.parameters)

    def _inv_time_transform(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.

        modes = self.state
        time_real = modes[:-self.n, :]
        time_imaginary = 1j*np.concatenate((np.zeros([1, self.m]), modes[-self.n:, :]), axis=0)
        complex_modes = np.concatenate((time_real + time_imaginary, np.zeros([1, self.m])), axis=0)
        complex_modes[1:, :] = complex_modes[1:, :]/np.sqrt(2)
        imaginary_space_modes = irfft(complex_modes, norm='ortho', axis=0)
        space_modes = np.concatenate((np.zeros(imaginary_space_modes.shape), imaginary_space_modes), axis=1)

        if inplace:
            self.state = space_modes
            self.basis = 's_modes'
            return self
        else:
            return self.__class__(state=space_modes, basis='s_modes', parameters=self.parameters)

    def to_fundamental_domain(self, half=0, **kwargs):
        """ Overwrite of parent method """
        if half == 0:
            f_domain = self.transform(to='field').state[:, :-int(self.M//2)]
        else:
            f_domain = self.transform(to='field').state[:, -int(self.M//2):]

        return self.__class__(state=f_domain, basis='field', parameters=(self.T, self.L / 2.0, 0.))


class ShiftReflectionOrbitKS(OrbitKS):

    def __init__(self, state=None, basis='modes', parameters=(0., 0., 0.), **kwargs):
        """ Orbit subclass for solutions with spatiotemporal shift-reflect symmetry



        Parameters
        ----------
        state
        basis
        T
        L
        kwargs

        Notes
        -----
        Technically could inherit some functions from AntisymmetricOrbitKS but in regards to the Physics
        going on it is more coherent to have it as a subclass of OrbitKS only.
        """
        super().__init__(state=state, basis=basis, parameters=parameters, **kwargs)

    def dx(self, power=1, return_array=False):
        """ Overwrite of parent method """

        if np.mod(power, 2):
            dxn_s_modes = swap_modes(np.multiply(self.elementwise_dxn(self.dx_parameters, power=power),
                                                 self.transform(to='s_modes').state), axis=1)
            # Typically have to keep odd ordered spatial derivatives as spatial modes or field.
            if return_array:
                return dxn_s_modes
            else:
                return self.__class__(state=dxn_s_modes, basis='s_modes', parameters=self.parameters)
        else:
            dxn_modes = np.multiply(self.elementwise_dxn(self.dx_parameters, power=power),
                                    self.transform(to='modes').state)
            if return_array:
                return dxn_modes
            else:
                return self.__class__(state=dxn_modes, basis='modes',
                                      parameters=self.parameters).transform(to=self.basis)

    @classmethod
    @lru_cache(maxsize=16)
    def elementwise_dxn(cls, dx_parameters, power=1):
        """ Matrix of temporal mode frequencies

        Creates and returns a matrix whose elements
        are the properly ordered spatial frequencies,
        which is the same shape as the spatiotemporal
        Fourier mode state. The elementwise product
        with a set of spatiotemporal Fourier modes
        is equivalent to taking a spatial derivative.

        Returns
        ----------
        matrix
            Matrix of spatial frequencies
        """
        q = cls._wave_vector(dx_parameters, power=power)
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        c1, c2 = so2_coefficients(power=power)
        # Create elementwise spatial frequency matrix
        if np.mod(power, 2):
            # If the order of the derivative is odd, need to apply to spatial modes not spacetime modes.
            dxn_multipliers = np.tile(np.concatenate((c1*q, c2*q), axis=1), (dx_parameters[-2], 1))
        else:
            # if order is even, make the frequencies into an array with same shape as modes; c1 = c2 when power is even.
            dxn_multipliers = np.tile(c1*q, (dx_parameters[-1], 1))
        return dxn_multipliers

    def _dx_matrix(self, power=1, **kwargs):
        """ Overwrite of parent method """
        basis = kwargs.get('basis', self.basis)
        # Define spatial wavenumber vector
        if basis == 's_modes':
            dx_n_matrix = np.kron(so2_generator(power=power), np.diag(self._wave_vector(self.dx_parameters,
                                                                                       power=power).ravel()))
            _dx_matrix_complete = np.kron(np.eye(self.N), dx_n_matrix)
        else:
            _, c = so2_coefficients(power=power)
            dx_n_matrix = c * np.diag(self._wave_vector(self.dx_parameters, power=power).ravel())
            _dx_matrix_complete = np.kron(np.eye(self.mode_shape[0]), dx_n_matrix)

        return _dx_matrix_complete

    def from_fundamental_domain(self):
        """ Reconstruct full field from discrete fundamental domain """
        field = np.concatenate((self.reflection().state, self.state), axis=0)
        return self.__class__(state=field, basis='field', parameters=(2*self.T, self.L, 0.))

    def _pad(self, size, axis=0):
        """ Overwrite of parent method """
        modes = self.transform(to='modes')
        if np.mod(size, 2):
            raise ValueError('New discretization size must be an even number, preferably a power of 2')
        else:
            if axis == 0:
                # Split into real and imaginary components, pad separately.
                first_half = modes.state[:-modes.n, :]
                second_half = modes.state[-modes.n:, :]
                padding_number = int((size-modes.N) // 2)
                padding = np.zeros([padding_number, modes.state.shape[1]])
                padded_modes = np.sqrt(size / modes.N) * np.concatenate((first_half, padding, second_half, padding),
                                                                        axis=0)
            else:
                padding_number = int((size-modes.M) // 2)
                padding = np.zeros([modes.state.shape[0], padding_number])
                padded_modes = np.sqrt(size / modes.M) * np.concatenate((modes.state, padding), axis=1)

        return self.__class__(state=padded_modes, basis='modes',
                              parameters=self.parameters).transform(to=self.basis)

    def _truncate(self, size, axis=0):
        """ Overwrite of parent method """
        modes = self.transform(to='modes')
        if np.mod(size, 2):
            raise ValueError('New discretization size must be an even number, preferably a power of 2')
        else:
            if axis == 0:
                truncate_number = int(size // 2) - 1
                first_half = modes.state[:truncate_number+1, :]
                second_half = modes.state[-modes.n:-modes.n+truncate_number, :]
                truncated_modes = np.sqrt(size / modes.N) * np.concatenate((first_half, second_half), axis=0)
            else:
                truncate_number = int(size // 2) - 1
                truncated_modes = np.sqrt(size / modes.M) * modes.state[:, :truncate_number]
        return self.__class__(state=truncated_modes, basis='modes',
                              parameters=self.parameters).transform(to=self.basis)

    def nonlinear(self, other, return_array=False):
        """ nonlinear computation of the nonlinear term of the Kuramoto-Sivashinsky equation

        """
        # Elementwise product, both self and other should be in physical field basis.
        assert (self.basis == 'field') and (other.basis == 'field')
        # to get around the special behavior of discrete symmetries
        if return_array:
            return 0.5 * self.statemul(other).dx(return_array=False).transform(to='modes').state
        else:
            return 0.5 * self.statemul(other).dx(return_array=False).transform(to='modes')

    def _jac_nonlin(self):
        """ The nonlinear component of the Jacobian matrix of the Kuramoto-Sivashinsky equation

        Returns
        -------
        nonlinear_dx : matrix
            Matrix which represents the nonlinear component of the Jacobian. The derivative of
            the nonlinear term, which is
            (D/DU) 1/2 d_x (u .* u) = (D/DU) 1/2 d_x F (diag(F^-1 u)^2)  = d_x F( diag(F^-1 u) F^-1).
            See
            Chu, K.T. A direct matrix method for computing analytical Jacobians of discretized nonlinear
            integro-differential equations. J. Comp. Phys. 2009
            for details.

        Notes
        -----
        The obvious way of computing this, represented above, is to multiply the linear operators
        corresponding to d_x F( diag(F^-1 u) F^-1). However, if we slightly rearrange things such that
        the spatial differential is taken on spatial modes, then this function generalizes to the subclasses
        with discrete symmetry.
        """

        _jac_nonlin_left = self._time_transform_matrix().dot(self._dx_matrix(basis='s_modes'))
        _jac_nonlin_middle = self._space_transform_matrix().dot(np.diag(self.transform(to='field').state.ravel()))
        _jac_nonlin_right = self._inv_spacetime_transform_matrix()
        _jac_nonlin = _jac_nonlin_left.dot(_jac_nonlin_middle).dot(_jac_nonlin_right)

        return _jac_nonlin

    @property
    def dt_parameters(self):
        return self.T, self.N, self.n, self.m

    @property
    def dx_parameters(self):
        return self.L, self.M, self.m,  self.N, max([self.N-1, 1]),

    @property
    def mode_shape(self):
        return max([self.N-1, 1]), self.m

    @property
    def dimensions(self):
        return self.T, self.L

    def _parse_state(self, state, basis, **kwargs):
        shp = state.shape
        self.state = state
        self.basis = basis
        if basis == 'modes':
            self.N, self.M = shp[0] + 1, 2*shp[1] + 2
        elif basis == 'field':
            self.N, self.M = shp
        elif basis == 's_modes':
            self.N, self.M = shp[0], shp[1]+2
        else:
            raise ValueError('basis is unrecognizable')
        self.n, self.m = max([int(self.N // 2) - 1,  1]), int(self.M // 2) - 1
        return self

    def _time_transform(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        modes = rfft(self.state, norm='ortho', axis=0)
        modes_real = modes.real[:-1, :-self.m] + modes.real[:-1, -self.m:]
        modes_imag = modes.imag[1:-1, :-self.m] + modes.imag[1:-1, -self.m:]
        spacetime_modes = np.concatenate((modes_real, modes_imag), axis=0)
        spacetime_modes[1:, :] = np.sqrt(2)*spacetime_modes[1:, :]
        if inplace:
            self.state = spacetime_modes
            self.basis = 'modes'
            return self
        else:
            return self.__class__(state=spacetime_modes, basis='modes', parameters=self.parameters)

    def _inv_time_transform(self, inplace=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        inplace : bool
            Whether or not to perform the operation "in place" (overwrite the current state if True).

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Take irfft, accounting for unitary normalization.
        assert self.basis == 'modes'
        modes = self.state
        even_indices = np.arange(0, self.N//2, 2)
        odd_indices = np.arange(1, self.N//2, 2)

        time_real = modes[:-self.n, :]
        time_imaginary = 1j*np.concatenate((np.zeros([1, self.m]), modes[-self.n:, :]), axis=0)
        complex_modes = np.concatenate((time_real + time_imaginary, np.zeros([1, self.m])), axis=0)
        complex_modes[1:, :] = complex_modes[1:, :]/np.sqrt(2)
        real_space, imaginary_space = complex_modes.copy(), complex_modes.copy()
        real_space[even_indices, :] = 0
        imaginary_space[odd_indices, :] = 0
        space_modes = irfft(np.concatenate((real_space, imaginary_space), axis=1), norm='ortho', axis=0)

        if inplace:
            self.state = space_modes
            self.basis = 's_modes'
            return self
        else:
            return self.__class__(state=space_modes, basis='s_modes', parameters=self.parameters)

    def _time_transform_matrix(self):
        """

        Notes
        -----
        This function and its inverse are the most confusing parts of the code by far.
        The reason is because in order to implement a symmetry invariant time RFFT that retains no
        redundant modes (constrained to be zero) we need to actually combine two halves of the
        full transform in an awkward way. the real and imaginary spatial mode components, when
        mapped to spatiotemporal modes, retain odd and even frequency indexed modes respectively.

        The best way I have come to think about this is that there are even/odd indexed Fourier transforms
        which each apply to half of the variables, but in order to take a matrix representation we need
        to "shuffle" these two operators in order to be compatible with the way the arrays are formatted.

        Compute FFT matrix by acting on the identity matrix columns (or rows, doesn't matter).
        This is a matrix that takes in a signal (time series) and outputs a set of real valued
        Fourier coefficients in the format [a_0, a_1, b_1, a_2, b_2, a_3, b_3, ... , a_n, b_n, a(N//2)]
        a = real component, b = imaginary component if complex valued Fourier transform was computed instead
        (up to some normalization factor).
        """
        ab_transform_formatter = np.zeros((self.N-1, 2*self.N), dtype=int)
        # binary checkerboard matrix
        ab_transform_formatter[1:-self.n:2, ::2] = 1
        ab_transform_formatter[:-self.n:2, 1::2] = 1
        ab_transform_formatter[-self.n+1::2, 1::2] = 1
        ab_transform_formatter[-self.n::2, ::2] = 1

        full_dft_mat = rfft(np.eye(self.N), norm='ortho', axis=0)
        time_dft_mat = np.concatenate((full_dft_mat[:-1, :].real, full_dft_mat[1:-1, :].imag), axis=0)
        time_dft_mat[1:, :] = np.sqrt(2)*time_dft_mat[1:, :]
        ab_time_dft_matrix = np.insert(time_dft_mat, np.arange(time_dft_mat.shape[1]), time_dft_mat, axis=1)
        full_time_transform_matrix = np.kron(ab_time_dft_matrix*ab_transform_formatter, np.eye(self.m))
        return full_time_transform_matrix

    def _inv_time_transform_matrix(self):
        """ Overwrite of parent method """

        ab_transform_formatter = np.zeros((2*self.N, self.N-1), dtype=int)
        ab_transform_formatter[::2, 1:-self.n:2] = 1
        ab_transform_formatter[1::2, :-self.n:2] = 1
        ab_transform_formatter[1::2, -self.n+1::2] = 1
        ab_transform_formatter[::2, -self.n::2] = 1

        imag_idft_matrix = irfft(1j*np.eye((self.N//2)+1), norm='ortho', axis=0)
        real_idft_matrix = irfft(np.eye((self.N//2)+1), norm='ortho', axis=0)
        time_idft_matrix = np.concatenate((real_idft_matrix[:, :-1], imag_idft_matrix[:, 1:-1]), axis=1)
        time_idft_matrix[:, 1:] = time_idft_matrix[:, 1:]/np.sqrt(2)
        ab_time_idft_matrix = np.insert(time_idft_matrix, np.arange(time_idft_matrix.shape[0]),
                                        time_idft_matrix, axis=0)

        full_inv_time_transform_matrix = np.kron(ab_time_idft_matrix*ab_transform_formatter,
                                                 np.eye(self.mode_shape[1]))
        return full_inv_time_transform_matrix

    def to_fundamental_domain(self, half=0):
        """ Overwrite of parent method """
        field = self.transform(to='field').state
        if half == 0:
            f_domain = field[-int(self.N // 2):, :]
        else:
            f_domain = field[:-int(self.N // 2), :]
        return self.__class__(state=f_domain, basis='field', parameters=(self.T / 2.0, self.L, 0.))


class EquilibriumOrbitKS(AntisymmetricOrbitKS):

    def __init__(self, state=None, basis='modes', parameters=(0., 0., 0.), **kwargs):
        """ Subclass for equilibrium solutions (all of which are antisymmetric w.r.t. space).
        Parameters
        ----------
        state
        basis
        T
        L
        S
        kwargs

        Notes
        -----
        For convenience, this subclass accepts any (even) value for the time discretization. Only a single time point
        is required however to fully represent the solution and therefore perform any computations. If the discretization
        size is greater than 1 then then different bases will have the following shapes: field (N, M). spatial modes =
        (N, m), spatiotemporal modes (1, m). In other words, discretizations of this type can still be used in
        the optimization codes but will be much more inefficient. The reason for this choice is because it is possible
        to start with a spatiotemporal orbit with no symmetry (i.e. OrbitKS) and still end up at an equilibrium
        solution. Therefore, I am accommodating transformations from other orbit types to EquilibriumOrbitKS. To
        make the computations more efficient all that is required is usage of the method
        self.optimize_for_calculations(), which converts N -> 1, making the shape of the state (1, M) in the
        physical field basis. Also can inherit more methods with this choice.
        More details are included in the thesis and in the documentation.
        While only the imaginary components of the spatial modes are non-zero, both real and imaginary components are
        kept to allow for odd order spatial derivatives, required for the nonlinear term. Other allowed operations such
        as rotation are preferably performed after converting to a different symmetry type such as AntisymmetricOrbitKS
        or OrbitKS.

                #dx
        #elementwise_dxn
        #_dx_matrix
        # from_fundamental_domain
        # _pad
        # _truncate
        # nonlinear
        # random_initial_condition
        # time_transform_matrix
        # inv_time_transform_matrix
        # time_transform
        # inv_time_transform
        # to_fundamental_domain

        """
        super().__init__(state=state, basis=basis, parameters=parameters, **kwargs)

    def state_vector(self):
        """ Overwrite of parent method """
        return np.concatenate((self.state.reshape(-1, 1),
                               np.array([[float(self.L)]])), axis=0)

    def from_fundamental_domain(self, inplace=False, **kwargs):
        """ Overwrite of parent method """
        return self.__class__(state=np.concatenate((self.reflection().state, self.state), axis=1),
                              basis='field', parameters=(0., 2.0*self.L, 0.))

    def from_numpy_array(self, state_array, **kwargs):
        """ Utility to convert from numpy array to orbithunter format for scipy wrappers.
        :param orbit:
        :param state_array:
        :param parameter_constraints:
        :return:

        Notes
        -----
        Written as a general method that covers all subclasses instead of writing individual methods.
        """
        mode_shape, mode_size = self.state.shape, self.state.size
        modes = state_array.ravel()[:mode_size]
        params_list = state_array.ravel()[mode_size:].tolist()
        L = float(tuple(params_list.pop(0) if not p and params_list else 0 for p in self.constraints.values())[0])
        return self.__class__(state=np.reshape(modes, mode_shape), basis='modes', parameters=(0., L, 0.))

    def _jac_lin(self):
        """ Extension of the OrbitKS method that includes the term for spatial translation symmetry"""
        return self._dx_matrix(power=2) + self._dx_matrix(power=4)

    def _jacobian_parameter_derivatives_concat(self, jac_, ):
        """ Concatenate parameter partial derivatives to Jacobian matrix

        Parameters
        ----------
        jac_ : np.ndArray,
        (N-1) * (M-2) dimensional array resultant from taking the derivative of the spatioatemporal mapping
        with respect to Fourier modes.
        parameter_constraints : tuple
        Flags which indicate which parameters are constrained; if unconstrained then need to augment the Jacobian
        with partial derivatives with respect to unconstrained parameters.

        Returns
        -------
        Jacobian augmented with parameter partial derivatives as columns. Required to solve for changes to period,
        space period in optimization process. Makes the system rectangular; needs to be solved by least squares type
        methods.

        """
        # If spatial period is not fixed, need to include dF/dL in jacobian matrix
        if not self.constraints['L']:
            self_field = self.transform(to='field')
            spatial_period_derivative = ((-2.0 / self.L) * self.dx(power=2, return_array=True)
                                         + (-4.0 / self.L) * self.dx(power=4, return_array=True)
                                         + (-1.0 / self.L) * self_field.nonlinear(self_field, return_array=True))
            jac_ = np.concatenate((jac_, spatial_period_derivative.reshape(-1, 1)), axis=1)

        return jac_

    def _pad(self, size, axis=0):
        """ Overwrite of parent method

        Notes
        -----
        If starting and ending in the spatiotemporal modes basis, this will only create an instance with a different
        value of time dimensionality attribute 'N'.
        """
        s_modes = self.transform(to='s_modes')
        if axis == 0:
            # Not technically zero-padding, just copying. Just can't be in temporal mode basis
            # because it is designed to only represent the zeroth modes.
            padded_s_modes = np.tile(s_modes.state[0, :].reshape(1, -1), (size, 1))
            return self.__class__(state=padded_s_modes, basis='s_modes',
                                  parameters=self.parameters, N=size).transform(to=self.basis)
        else:
            # Split into real and imaginary components, pad separately.
            complex_modes = s_modes.state[:, -s_modes.m:]
            real_modes = np.zeros(complex_modes.shape)
            padding_number = int((size-s_modes.M) // 2)
            padding = np.zeros([s_modes.state.shape[0], padding_number])
            padded_modes = np.sqrt(size / s_modes.M) * np.concatenate((real_modes, padding,
                                                                       complex_modes, padding), axis=1)
            return self.__class__(state=padded_modes, basis='s_modes',
                                  parameters=self.parameters).transform(to=self.basis)

    def _truncate(self, size, axis=0):
        """ Overwrite of parent method """
        if axis == 0:
            s_modes = self.transform(to='s_modes')
            truncated_s_modes = s_modes.state[-size:, :]
            return self.__class__(state=truncated_s_modes, basis='s_modes',
                                  parameters=self.parameters).transform(to=self.basis)
        else:
            modes = self.transform(to='modes')
            truncate_number = int(size // 2) - 1
            truncated_modes = modes.state[:, :truncate_number]
            return self.__class__(state=truncated_modes,  basis='modes',
                                  parameters=self.parameters, N=self.N).transform(to=self.basis)

    def rmatvec_parameters(self, self_field, other):
        other_modes_in_vector_form = other.state.ravel()
        if not self.constraints['L']:
            # change in L, dL, equal to DF/DL * v
            rmatvec_L = ((-2.0 / self.L) * self.dx(power=2, return_array=True)
                         + (-4.0 / self.L) * self.dx(power=4, return_array=True)
                         + (-1.0 / self.L) * self_field.nonlinear(self_field, return_array=True)
                         ).ravel().dot(other_modes_in_vector_form)
        else:
            rmatvec_L = 0

        return 0., rmatvec_L, 0.

    def _parse_parameters(self, parameters, **kwargs):
        # New addition, keep track of constraints via attribute instead of passing them around everywhere.
        self.constraints = kwargs.get('constraints', {'L': False})

        # If parameter dictionary was passed, then unpack that.
        L = parameters[1]

        # The default value of nonzero_parameters is False. If its true, assign random value to L
        if L == 0. and kwargs.get('nonzero_parameters', False):
            if kwargs.get('seed', None) is not None:
                np.random.seed(kwargs.get('seed', None)+1)
            self.L = (kwargs.get('L_min', 22.)
                      + (kwargs.get('L_max', 66.) - kwargs.get('L_min', 22.))*np.random.rand())
        else:
            self.L = float(L)
        # for the sake of uniformity of save format, technically 0 will be returned even if not defined because
        # of __getattr__ definition.
        self.T = 0.
        self.S = 0.

    def _parameter_preconditioning(self, dt_params, dx_params):
        parameter_multipliers = []
        if not self.constraints['L']:
            parameter_multipliers.append(dx_params[0]**-4)
        return np.array(parameter_multipliers)

    def _random_initial_condition(self, parameters, **kwargs):
        """ Initial a set of random spatiotemporal Fourier modes
        Parameters
        ----------
        T : float
            Time period
        L : float
            Space period
        **kwargs
            time_scale : int
                The number of temporal frequencies to keep after truncation.
            space_scale : int
                The number of spatial frequencies to get after truncation.
        Returns
        -------
        self :
            OrbitKS whose state has been modified to be a set of random Fourier modes.
        Notes
        -----
        These are the initial condition generators that I find the most useful. If a different method is
        desired, simply pass the array as 'state' variable to __init__.
        """

        spectrum = kwargs.get('spectrum', 'gaussian')

        # also accepts N and M as kwargs
        self.N, self.M = self.__class__.parameter_based_discretization(parameters, N=1)
        self.n, self.m = 1, int(self.M // 2) - 1
        xscale = kwargs.get('xscale', int(np.round(self.L / (2*pi*np.sqrt(2)))))
        xvar = kwargs.get('xvar', np.sqrt(xscale))

        # I think this is the easiest way to get symmetry-dependent Fourier mode arrays' shapes.
        # power = 2 b.c. odd powers not defined for spacetime modes for discrete symmetries.
        space_ = np.sqrt((self.L / (2*pi))**2 * np.abs(self.elementwise_dxn(self.dx_parameters,
                                                                            power=2))).astype(int)
        np.random.seed(kwargs.get('seed', None))
        random_modes = np.random.randn(*self.mode_shape)
        # piece-wise constant + exponential
        # linear-component based. multiply by preconditioner?
        # random modes, no modulation.

        if spectrum == 'gaussian':
            # spacetime gaussian modulation
            gaussian_modulator = np.exp(-(space_ - xscale)**2/(2*xvar))
            modes = np.multiply(gaussian_modulator, random_modes)
        elif spectrum == 'piecewise-exponential':
            # space scaling is constant up until certain wave number then exponential decrease
            # time scaling is static
            space_[space_ <= xscale] = xscale
            p_exp_modulator = np.exp(-1.0 * np.abs(space_ - xscale) / xvar)
            modes = np.multiply(p_exp_modulator, random_modes)

        elif spectrum == 'exponential':
            # exponential decrease away from selected spatial scale
            exp_modulator = np.exp(-1.0 * np.abs(space_- xscale) / xvar)
            modes = np.multiply(exp_modulator, random_modes)
        elif spectrum == 'linear':
            # so we get qk^2 - qk^4
            mollifier = (self.elementwise_dxn(self.dx_parameters, power=2)
                         + self.elementwise_dxn(self.dx_parameters, power=4))
            # The sign of the spectrum doesn't matter because modes were random anyway.
            modes = np.divide(random_modes, mollifier)
        elif spectrum == 'linear-exponential':
            # so we get qk^2 - qk^4
            mollifier = -1.0*np.abs((2*pi*xscale/self.L)**2-(2*pi*xscale/self.L)**4
                                    -(2*pi*space_ / self.L)**2+(2*pi*space_/self.L)**4)
            modes = np.multiply(mollifier, random_modes)
        elif spectrum == 'plateau-linear':
            plateau = np.where(space_[space_ <= xscale])
            # so we get qk^2 - qk^4
            mollifier = (2*pi*space_/self.L)**2 - (2*pi*space_/self.L)**4
            mollifier[plateau] = 1
            modes = np.divide(random_modes, np.abs(mollifier))
        else:
            modes = random_modes

        self.state = modes
        self.basis = 'modes'
        return self.rescale(kwargs.get('magnitude', 3.5), inplace=True,
                            method=kwargs.get('rescale_method', 'absolute'))

    def flatten_time_dimension(self):
        """ Discard redundant field information.

        Returns
        -------
        EquilibriumOrbitKS
            Instance wherein the new field has a single time discretization point.

        Notes
        -----
        Equivalent to calling _truncate with size=1, axis=0.
        This method exists because when it is called it is much more explicit w.r.t. what is being done.
        """
        field_single_time_point = self.transform(to='field').state[0, :].reshape(1, -1)
        # Keep whatever value of time period T was stored in the original orbit for transformation purposes.
        return self.__class__(state=field_single_time_point, basis='field',
                              parameters=self.parameters).transform(to=self.basis)

    @property
    def dx_parameters(self):
        return self.L, self.M, self.m, self.N, 1

    @property
    def parameters(self):
        """

        Returns
        -------
        tuple
        """
        return 0., self.L, 0.

    @property
    def mode_shape(self):
        return 1, self.m

    @property
    def dimensions(self):
        return 0., self.L

    @classmethod
    def glue_parameters(cls, zipped_parameters, glue_shape=(1, 1)):
        """ Class method for handling parameters in gluing

        Parameters
        ----------
        parameter_dict_with_bundled_values
        axis

        Returns
        -------

        Notes
        -----
        The shift will be calculated when the parameters are passed to the instance because of the 'frame':'physical'
        dict kay value pair.

        """

        L_array = np.array(zipped_parameters[1])

        if glue_shape[0] > 1:
            raise ValueError('Trying to glue EquilibriumOrbitKS() in time is contradictory.')
        elif glue_shape[0] == 1 and glue_shape[1] > 1:
            glued_parameters = (0, np.sum(L_array), 0.)
        else:
            # Gluing shouldn't really be used if there is literally no gluing occuring, i.e. glue_shape = (1,1),
            # but just for the sake of completeness.
            glued_parameters = (0, float(L_array), 0.)

        return glued_parameters

    def _parse_state(self, state, basis, **kwargs):
        shp = state.shape
        if len(shp) == 1:
            state = state.reshape(1, -1)
            shp = state.shape
        self.state = state
        self.basis = basis
        if basis == 'modes':
            self.state = self.state[0, :].reshape(1, -1)
            if kwargs.get('N', None) is not None:
                self.N = kwargs.get('N', None)
            else:
                self.N = 1
            self.M = 2 * shp[1] + 2
        elif basis == 'field':
            self.N, self.M = shp
        elif basis == 's_modes':
            self.N, self.M = shp[0], shp[1] + 2
        else:
            raise ValueError('basis is unrecognizable')
        # To allow for multiple time point fields and spatial modes, for plotting purposes mainly.
        self.n, self.m = 1, int(self.M // 2) - 1
        return self

    def precondition(self, parameters, **kwargs):
        """ Precondition a vector with the inverse (aboslute value) of linear spatial terms

        Parameters
        ----------

        target : OrbitKS
            OrbitKS to precondition
        parameter_constraints : (bool, bool)
            Whether or not period T or spatial period L are fixed.

        Returns
        -------
        target : OrbitKS
            Return the OrbitKS instance, modified by preconditioning.

        Notes
        -----
        Often we want to precondition a state derived from a mapping or rmatvec (gradient descent step),
        with respect to another orbit's (current state's) parameters. By passing parameters we can access the
        cached classmethods.

        I never preconditioned the spatial shift for relative periodic solutions so I don't include it here.
        """
        _, dx_params = parameters
        p_multipliers = 1.0 / (np.abs(self.elementwise_dxn(dx_params, power=2))
                               + self.elementwise_dxn(dx_params, power=4))
        self.state = np.multiply(self.state, p_multipliers)
        param_power = kwargs.get('pexp', 4)
        # Precondition the change in T and L so that they do not dominate
        if not self.constraints['L']:
            self.L = self.L / (dx_params[0]**param_power)

        return self

    def preconditioner(self, parameters, **kwargs):
        """ Preconditioning matrix

        Parameters
        ----------
        parameter_constraints : (bool, bool)
            Whether or not period T or spatial period L are fixed.
        side : str
            Takes values 'left' or 'right'. This is an accomodation for
            the typically rectangular Jacobian matrix.

        Returns
        -------
        matrix :
            Preconditioning matrix

        """
        # Preconditioner is the inverse of the absolute value of the linear spatial derivative operators.
        # The construction of the matrix (i.e. here) is typically used in lstsq; therefore return right hand
        # preconditioner by default.
        side = kwargs.get('side', 'right')
        dt_params, dx_params = parameters
        p_multipliers = (1.0 / (+ np.abs(self.elementwise_dxn(dx_params, power=2))
                                + self.elementwise_dxn(dx_params, power=4))).ravel()

        # If including parameters, need an extra diagonal matrix to account for this (right-side preconditioning)
        if side == 'right':
            return np.diag(np.concatenate((p_multipliers,
                                           self._parameter_preconditioning(dt_params, dx_params)), axis=0))
        else:
            return np.diag(p_multipliers)

    def rmatvec(self, other, **kwargs):
        """ Overwrite of parent method """
        assert (self.basis == 'modes') and (other.basis == 'modes')
        self_field = self.transform(to='field')
        rmatvec_modes = (other.dx(power=2, return_array=True)
                         + other.dx(power=4, return_array=True)
                         + self_field.rnonlinear(other, return_array=True))

        other_modes_in_vector_form = other.state.ravel()
        if not self.constraints['L']:
            # change in L, dL, equal to DF/DL * v
            rmatvec_L = ((-2.0 / self.L) * self.dx(power=2, return_array=True)
                         + (-4.0 / self.L) * self.dx(power=4, return_array=True)
                         + (-1.0 / self.L) * self_field.nonlinear(self_field, return_array=True)
                         ).ravel().dot(other_modes_in_vector_form)
        else:
            rmatvec_L = 0

        return self.__class__(state=rmatvec_modes, basis='modes', parameters=(0., rmatvec_L, 0.))

    def spatiotemporal_mapping(self, **kwargs):
        """ The Kuramoto-Sivashinsky equation evaluated at the current state.

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is the spatiotamporal fourier modes resulting from the calculation of the K-S equation:
            OrbitKS.state = u_t + u_xx + u_xxxx + 1/2 (u^2)_x
        :return:
        """
        assert self.basis == 'modes', 'Convert to spatiotemporal Fourier mode basis before computations.'
        # to avoid two IFFT calls, convert before nonlinear product
        orbit_field = self.transform(to='field')
        mapping_modes = (self.dx(power=2, return_array=True)
                         + self.dx(power=4, return_array=True)
                         + orbit_field.nonlinear(orbit_field, return_array=True))
        return self.__class__(state=mapping_modes, basis='modes', parameters=self.parameters)

    def verify_integrity(self):
        """ Check whether the orbit converged to an equilibrium or close-to-zero solution """
        # Take the L_2 norm of the field, if uniformly close to zero, the magnitude will be very small.
        field_orbit = self.transform(to='field')

        # See if the L_2 norm is beneath a threshold value, if so, replace with zeros.
        if field_orbit.norm() < 10**-5:
            code = 4
            return self.__class__(state=np.zeros([self.N, self.M]), basis='field',
                                  parameters=self.parameters).transform(to=self.basis), code
        else:
            return self, 1

    def _inv_time_transform_matrix(self):
        """ Overwrite of parent method

        Notes
        -----
        Originally this transform just selected the antisymmetric spatial modes (imaginary component),
        but in order to be consistent with all other time transforms, I will actually apply the normalization
        constant associated with a forward in time transformation. The reason for this is for comparison
        of states between different subclasses.
        """
        return np.tile(np.concatenate((0*np.eye(self.m), np.eye(self.m)), axis=0), (self.N, 1))

    def _time_transform_matrix(self):
        """ Overwrite of parent method """

        time_dft_mat = np.tile(np.concatenate((0*np.eye(self.m), np.eye(self.m)), axis=1), (1, self.N))
        time_dft_mat[:, 2*self.m:] = 0
        return time_dft_mat

    def _time_transform(self, inplace=False):
        """ Overwrite of parent method

        Notes
        -----
        Taking the RFFT, with orthogonal normalization, of a constant time series defined on N points is equivalent
        to multiplying the constant value by sqrt(N). This is because the transform sums over N repeats of the same
        value and then divides by 1/sqrt(N). i.e. (N * C)/sqrt(N) = sqrt(N) * C. Therefore we can save some time by
        just doing this without calling the rfft function.
        """
        # Select the nonzero (imaginary) components of modes and transform in time (w.r.t. axis=0).
        spacetime_modes = self.state[0, -self.m:].reshape(1, -1)
        if inplace:
            self.state = spacetime_modes
            self.basis = 'modes'
            return self
        else:
            return self.__class__(state=spacetime_modes, basis='modes',
                                  parameters=self.parameters, N=self.N)

    def _inv_time_transform(self, inplace=False):
        """ Overwrite of parent method

        Notes
        -----
        Taking the IRFFT, with orthogonal normalization is equivalent to dividing by the normalization constant; because
        there would only be
        """
        real = np.zeros(self.state.shape)
        imaginary = self.state
        spatial_modes = np.tile(np.concatenate((real, imaginary), axis=1), (self.N, 1))
        if inplace:
            self.state = spatial_modes
            self.basis = 's_modes'
            return self
        else:
            return self.__class__(state=spatial_modes, basis='s_modes',
                                  parameters=self.parameters, N=self.N)

    def to_fundamental_domain(self, half=0, **kwargs):
        """ Overwrite of parent method """
        if half == 0:
            f_domain = self.transform(to='field').state[:, :-int(self.M//2)]
        else:
            f_domain = self.transform(to='field').state[:, -int(self.M//2):]
        return self.__class__(state=f_domain, basis='field', parameters=(0., self.L / 2.0, 0.))


class RelativeEquilibriumOrbitKS(RelativeOrbitKS):

    def __init__(self, state=None, basis='modes', parameters=(0., 0., 0.), frame='comoving', **kwargs):
        super().__init__(state=state, basis=basis, parameters=parameters, frame=frame, **kwargs)

    def dt(self, power=1, return_array=False):
        """ A time derivative of the current state.

        Parameters
        ----------
        power :int
            The order of the derivative.

        Returns
        ----------
        orbit_dtn : OrbitKS or subclass instance
            The class instance whose state is the time derivative in
            the spatiotemporal mode basis.
        """
        if self.frame == 'comoving':
            if return_array:
                return np.zeros(self.state.shape)
            else:
                return self.__class__(state=np.zeros(self.state.shape), basis=self.basis,
                                      parameters=self.parameters)
        else:
            raise ValueError(
                'Attempting to compute time derivative of ' + str(self) + ' in physical reference frame.'
                + 'If this is truly desired, convert to RelativeOrbitKS first.')

    def flatten_time_dimension(self):
        """ Discard redundant field information.

        Returns
        -------
        EquilibriumOrbitKS
            Instance wherein the new field has a single time discretization point.

        Notes
        -----
        Equivalent to calling _truncate with size=1, axis=0.
        This method exists because when it is called it is much more explicit w.r.t. what is being done.
        """
        field_single_time_point = self.transform(to='field').state[0, :].reshape(1, -1)
        # Keep whatever value of time period T was stored in the original orbit for transformation purposes.
        return self.__class__(state=field_single_time_point, basis='field',
                              parameters=self.parameters).transform(to=self.basis)

    def from_fundamental_domain(self):
        """ For compatibility purposes with plotting and other utilities """
        return self.change_reference_frame(to='physical')

    def _jac_lin(self):
        """ Extension of the OrbitKS method that includes the term for spatial translation symmetry"""
        return self._dx_matrix(power=2) + self._dx_matrix(power=4) + self.comoving_matrix()

    def _jacobian_parameter_derivatives_concat(self, jac_):
        """ Concatenate parameter partial derivatives to Jacobian matrix

        Parameters
        ----------
        jac_ : np.ndArray,
        (N-1) * (M-2) dimensional array resultant from taking the derivative of the spatioatemporal mapping
        with respect to Fourier modes.
        parameter_constraints : tuple
        Flags which indicate which parameters are constrained; if unconstrained then need to augment the Jacobian
        with partial derivatives with respect to unconstrained parameters.

        Returns
        -------
        Jacobian augmented with parameter partial derivatives as columns. Required to solve for changes to period,
        space period in optimization process. Makes the system rectangular; needs to be solved by least squares type
        methods.

        """
        # If period is not fixed, need to include dF/dT in jacobian matrix
        if not self.constraints['T']:
            time_period_derivative = (-1.0 / self.T)*self.comoving_mapping_component(return_array=True).reshape(-1, 1)
            jac_ = np.concatenate((jac_, time_period_derivative), axis=1)

        # If spatial period is not fixed, need to include dF/dL in jacobian matrix
        if not self.constraints['L']:
            self_field = self.transform(to='field')
            spatial_period_derivative = ((-2.0 / self.L) * self.dx(power=2, return_array=True)
                                          + (-4.0 / self.L) * self.dx(power=4, return_array=True)
                                          + (-1.0 / self.L) * self_field.nonlinear(self_field, return_array=True))
            jac_ = np.concatenate((jac_, spatial_period_derivative.reshape(-1, 1)), axis=1)

        if not self.constraints['S']:
            spatial_shift_derivatives = (-1.0 / self.T)*self.dx(return_array=True)
            jac_ = np.concatenate((jac_, spatial_shift_derivatives.reshape(-1, 1)), axis=1)

        return jac_

    def _pad(self, size, axis=0):
        """ Overwrite of parent method

        Notes
        -----
        If starting and ending in the spatiotemporal modes basis, this will only create an instance with a different
        value of time dimensionality attribute 'N'.
        """
        assert self.frame == 'comoving', 'Transform to comoving frame before padding modes'
        s_modes = self.transform(to='s_modes')
        if axis == 0:
            # Not technically zero-padding, just copying. Just can't be in temporal mode basis
            # because it is designed to only represent the zeroth modes.
            paddeds_s_modes = np.tile(s_modes.state[-1, :].reshape(1, -1), (size, 1))
            return self.__class__(state=paddeds_s_modes, basis='s_modes',
                                  parameters=self.parameters).transform(to=self.basis)
        else:
            # Split into real and imaginary components, pad separately.
            first_half = s_modes.state[:, :-s_modes.m]
            second_half = s_modes.state[:, -s_modes.m:]
            padding_number = int((size-s_modes.M) // 2)
            padding = np.zeros([s_modes.state.shape[0], padding_number])
            padded_modes = np.sqrt(size / s_modes.M) * np.concatenate((first_half, padding,
                                                                       second_half, padding), axis=1)
            return self.__class__(state=padded_modes, basis='s_modes',
                                  parameters=self.parameters).transform(to=self.basis)

    def _truncate(self, size, axis=0):
        """ Decrease the size of the discretization via truncation

        Parameters
        -----------
        size : int
            The new size of the discretization, must be an even integer
            smaller than the current size of the discretization.
        dimension : str
            Takes values 'space' or 'time'. The dimension that will be truncated.

        Returns
        -------
        OrbitKS
            OrbitKS instance with smaller discretization. Always transforming to spatial mode basis because it
            represents the basis which has the most general transformations and the optimal number of operations.
            E.g. transforming to 'field' from 'modes' takes more work than transforming to 's_modes'.
        """
        assert self.frame == 'comoving', 'Transform to comoving frame before truncating modes'
        if axis == 0:
            truncated_s_modes = self.transform(to='s_modes').state[-size:, :]
            self.__class__(state=truncated_s_modes, basis='s_modes', parameters=self.parameters
                           ).transform(to=self.basis)
        else:
            truncate_number = int(size // 2) - 1
            # Split into real and imaginary components, truncate separately.
            s_modes = self.transform(to='s_modes')
            first_half = s_modes.state[:, :truncate_number]
            second_half = s_modes.state[:, -s_modes.m:-s_modes.m + truncate_number]
            truncated_s_modes = np.sqrt(size / s_modes.M) * np.concatenate((first_half, second_half), axis=1)
        return self.__class__(state=truncated_s_modes, basis=self.basis,
                              parameters=self.parameters).transform(to=self.basis)

    @property
    def dt_parameters(self):
        return self.T, self.N, self.n, self.M-2

    @property
    def dx_parameters(self):
        return self.L, self.M, self.m, 1

    @property
    def mode_shape(self):
        return 1, self.M-2

    @property
    def dimensions(self):
        return self.T, self.L

    def _parse_state(self, state, basis, **kwargs):
        # This is the best way I've found for passing modes but also wanting N != 1. without specifying
        # the keyword argument.
        shp = state.shape
        if len(shp) == 1:
            state = state.reshape(1, -1)
            shp = state.shape
        self.state = state
        self.basis = basis
        if basis == 'modes':
            self.state = self.state[0, :].reshape(1, -1)
            if kwargs.get('N', None) is not None:
                self.N = kwargs.get('N', None)
            else:
                self.N = 1
            self.M = shp[1] + 2
        elif basis == 'field':
            self.N, self.M = shp
        elif basis == 's_modes':
            self.N, self.M = shp[0], shp[1] + 2
        else:
            raise ValueError('basis is unrecognizable')
        # To allow for multiple time point fields and spatial modes, for plotting purposes.
        expanded_time_dimension = kwargs.get('N', 1)
        if expanded_time_dimension != 1:
            self.N = expanded_time_dimension
        self.n, self.m = 1, int(self.M // 2) - 1
        return self

    def _random_initial_condition(self, parameters, **kwargs):
        """ Initial a set of random spatiotemporal Fourier modes
        Parameters
        ----------
        T : float
            Time period
        L : float
            Space period
        **kwargs
            time_scale : int
                The number of temporal frequencies to keep after truncation.
            space_scale : int
                The number of spatial frequencies to get after truncation.
        Returns
        -------
        self :
            OrbitKS whose state has been modified to be a set of random Fourier modes.
        Notes
        -----
        These are the initial condition generators that I find the most useful. If a different method is
        desired, simply pass the array as 'state' variable to __init__.
        """

        spectrum = kwargs.get('spectrum', 'gaussian')

        # also accepts N and M as kwargs
        self.N, self.M = self.parameter_based_discretization(parameters, N=1)
        self.n, self.m = 1, int(self.M // 2) - 1

        tscale = kwargs.get('tscale', int(np.round(self.T / 20.)))
        xscale = kwargs.get('xscale', int(np.round(self.L / (2*pi*np.sqrt(2)))))
        xvar = kwargs.get('xvar', np.sqrt(xscale))
        tvar = kwargs.get('tvar', np.sqrt(tscale))

        # I think this is the easiest way to get symmetry-dependent Fourier mode arrays' shapes.
        # power = 2 b.c. odd powers not defined for spacetime modes for discrete symmetries.
        space_ = np.sqrt((self.L / (2*pi))**2 * np.abs(self.elementwise_dxn(self.dx_parameters,
                                                                            power=2))).astype(int)
        time_ = (self.T / (2*pi)) * np.abs(self.elementwise_dtn(self.dt_parameters))
        np.random.seed(kwargs.get('seed', None))
        random_modes = np.random.randn(*self.mode_shape)
        # piece-wise constant + exponential
        # linear-component based. multiply by preconditioner?
        # random modes, no modulation.

        if spectrum == 'gaussian':
            # spacetime gaussian modulation
            gaussian_modulator = np.exp(-((space_ - xscale)**2/(2*xvar)) - ((time_ - tscale)**2 / (2*tvar)))
            modes = np.multiply(gaussian_modulator, random_modes)

        elif spectrum == 'plateau-exponential':
            # space scaling is constant up until certain wave number then exponential decrease
            # time scaling is static
            time_[time_ > tscale] = 0.
            time_[time_ != 0.] = 1.
            space_[space_ <= xscale] = xscale
            exp_modulator = np.exp(-1.0 * np.abs(space_ - xscale) / xvar)
            p_exp_modulator = np.multiply(time_, exp_modulator)
            modes = np.multiply(p_exp_modulator, random_modes)

        elif spectrum == 'exponential':
            # exponential decrease away from selected spatial scale
            time_[time_ > tscale] = 0.
            time_[time_ != 0.] = 1.
            exp_modulator = np.exp(-1.0 * np.abs(space_- xscale) / xvar)
            p_exp_modulator = np.multiply(time_, exp_modulator)
            modes = np.multiply(p_exp_modulator, random_modes)

        elif spectrum == 'linear':
            # Modulate the spectrum using the spatial linear operator; equivalent to preconditioning.
            time_[time_ <= tscale] = 1.
            time_[time_ != 1.] = 0.
            # so we get qk^2 - qk^4
            mollifier = -1.0 * (self.elementwise_dxn(self.dx_parameters, power=2)
                                      + self.elementwise_dxn(self.dx_parameters, power=4))
            modulated_modes = np.divide(random_modes, mollifier)
            modes = np.multiply(time_, modulated_modes)

        elif spectrum == 'linear-exponential':
            # Modulate the spectrum using the spatial linear operator; equivalent to preconditioning.
            time_[time_ <= tscale] = 1.
            time_[time_ != 1.] = 0.
            # so we get qk^2 - qk^4
            mollifier = -(((2*pi*xscale/self.L)**2-(2*pi*xscale/self.L)**4)
                                -((2*pi*space_/self.L)**2-(2*pi*space_/self.L)**4))
            modulated_modes = np.divide(random_modes, mollifier)
            modes = np.multiply(time_, modulated_modes)

        elif spectrum == 'plateau-linear':
            # Modulate the spectrum using the spatial linear operator; equivalent to preconditioning.
            time_[time_ <= tscale] = 1.
            time_[time_ != 1.] = 0.
            plateau = np.where(space_[space_ <= xscale])
            # so we get qk^2 - qk^4
            mollifier = (2*pi*space_/self.L)**2 - (2*pi*space_/self.L)**4
            mollifier[plateau] = 1
            modulated_modes = np.divide(random_modes, np.abs(mollifier))
            modes = np.multiply(time_, modulated_modes)

        else:
            modes = random_modes

        self.state = modes
        self.basis = 'modes'
        return self.rescale(kwargs.get('magnitude', 2.5), inplace=True,
                            method=kwargs.get('rescale_method', 'absolute'))

    def spatiotemporal_mapping(self, **kwargs):
        """ The Kuramoto-Sivashinsky equation evaluated at the current state.

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is the spatiotamporal fourier modes resulting from the calculation of the K-S equation:
            OrbitKS.state = u_t + u_xx + u_xxxx + 1/2 (u^2)_x
        :return:
        """
        # to avoid two IFFT calls, convert before nonlinear product
        modes = self.transform(to='modes')
        field = self.transform(to='field')
        mapping_modes = (modes.dx(power=2, return_array=True)
                         + modes.dx(power=4, return_array=True)
                         + field.nonlinear(field, return_array=True)
                         + modes.comoving_mapping_component(return_array=True))
        return self.__class__(state=mapping_modes, basis='modes', parameters=self.parameters)

    def state_vector(self):
        """ Vector which completely describes the orbit."""
        return np.concatenate((self.state.reshape(-1, 1),
                               np.array([[float(self.T)]]),
                               np.array([[float(self.L)]]),
                               np.array([[float(self.S)]])), axis=0)

    def verify_integrity(self):
        """ Check whether the orbit converged to an equilibrium or close-to-zero solution """
        # Take the L_2 norm of the field, if uniformly close to zero, the magnitude will be very small.
        orbit_with_inverted_shift = self.copy()
        orbit_with_inverted_shift.S = -self.S
        residual_imported_S = self.residual()
        residual_negated_S = orbit_with_inverted_shift.residual()
        if residual_imported_S > residual_negated_S:
            orbit_ = orbit_with_inverted_shift
        else:
            orbit_ = self.copy()

        # Take the L_2 norm of the field, if uniformly close to zero, the magnitude will be very small.
        field_orbit = orbit_.transform(to='field')
        zero_check = field_orbit.norm()
        if zero_check < 10**-5:
            code = 4
            return RelativeEquilibriumOrbitKS(state=np.zeros(self.field_shape), basis='field',
                                              parameters=self.parameters).transform(to=self.basis), code
        else:
            code = 1
            return orbit_, code

    def _inv_time_transform_matrix(self):
        """ Overwrite of parent method

        Notes
        -----
        Originally this transform just selected the antisymmetric spatial modes (imaginary component),
        but in order to be consistent with all other time transforms, I will actually apply the normalization
        constant associated with a forward in time transformation. The reason for this is for comparison
        of states between different subclasses.
        """
        return np.tile(np.eye(self.M-2), (self.N, 1))

    def _time_transform_matrix(self):
        """ Overwrite of parent method

        Notes
        -----
        Input state is [N, M-2] dimensional array which is to be sliced to return only the last row.
        N * (M-2) repeats of modes coming in, M-2 coming out, so M-2 rows.

        """

        dft_mat = np.tile(np.eye(self.M-2), (1, self.N))
        dft_mat[:, self.M-2:] = 0
        return dft_mat

    def _time_transform(self, inplace=False):
        """ Overwrite of parent method

        Notes
        -----
        Taking the RFFT, with orthogonal normalization, of a constant time series defined on N points is equivalent
        to multiplying the constant value by sqrt(N). This is because the transform sums over N repeats of the same
        value and then divides by 1/sqrt(N). i.e. (N * C)/sqrt(N) = sqrt(N) * C. Therefore we can save some time by
        just doing this without calling the rfft function.

        This always returns a single instant in time, for solving purposes; if N != 1 then computations will work
        but will be much less efficient.

        Originally wanted to include normalization but it just screws things up given how the modes are truncated.
        """
        # Select the nonzero (imaginary) components of modes and transform in time (w.r.t. axis=0).
        spacetime_modes = self.state[0, :].reshape(1, -1)
        if inplace:
            self.state = spacetime_modes
            self.basis = 'modes'
            return self
        else:
            return self.__class__(state=spacetime_modes, basis='modes',
                                  parameters=self.parameters, N=self.N)

    def _inv_time_transform(self, inplace=False):
        """ Overwrite of parent method

        Notes
        -----
        Taking the IRFFT, with orthogonal normalization is equivalent to dividing by the normalization constant; because
        there would only be
        """
        spatial_modes = np.tile(self.state[0, :].reshape(1, -1), (self.N, 1))
        if inplace:
            self.state = spatial_modes
            self.basis = 's_modes'
            return self
        else:
            return self.__class__(state=spatial_modes, basis='s_modes', parameters=self.parameters)

    def to_fundamental_domain(self):
        return self.change_reference_frame(to='physical')


def ks_fpo_dictionary(tileset='default', comoving=False, rescaled=False, **kwargs):
    """ Template tiles for Kuramoto-Sivashinsky equation.


    Parameters
    ----------
    padded : bool
    Whether to use the zero-padded versions of the tiles
    comoving : bool
    Whether to use the defect tile in the physical or comoving frame.

    Returns
    -------
    tile_dict : dict
    Dictionary which contains defect, streak, wiggle tiles for use in tiling and gluing.

    Notes
    -----
    The dictionary is setup as follows : {0: streak, 1: defect, 2: wiggle}
    """
    fpo_filenames = []
    directory = os.path.abspath(os.path.join(__file__, '../../../data/ks/tiles/', ''.join(['./', tileset])))
    if rescaled:
        directory = os.path.abspath(os.path.join(directory, './rescaled/'))

    # streak orbit
    fpo_filenames.append(os.path.abspath(os.path.join(directory, './OrbitKS_streak.h5')))

    if comoving:
        # padded defect orbit in physical frame.
        fpo_filenames.append(os.path.abspath(os.path.join(directory, './OrbitKS_defect_comoving.h5')))
    else:
        # padded defect Orbit in comoving frame
        fpo_filenames.append(os.path.abspath(os.path.join(directory, './OrbitKS_defect.h5')))

    # wiggle orbit
    fpo_filenames.append(os.path.abspath(os.path.join(directory, './OrbitKS_wiggle.h5')))

    return dict(zip(range(len(fpo_filenames)), fpo_filenames))


def _parsing_dictionary():
    class_dict = {'base': OrbitKS, 'none': OrbitKS, 'full': OrbitKS, 'OrbitKS': OrbitKS,
                  'anti': AntisymmetricOrbitKS, 'AntisymmetricOrbitKS': AntisymmetricOrbitKS,
                  'ppo': ShiftReflectionOrbitKS, 'ShiftReflectionOrbitKS': ShiftReflectionOrbitKS,
                  'rpo': RelativeOrbitKS, 'RelativeOrbitKS': RelativeOrbitKS,
                  'eqva': EquilibriumOrbitKS, 'EquilibriumOrbitKS': EquilibriumOrbitKS,
                  'reqva': RelativeEquilibriumOrbitKS, 'RelativeEquilibriumOrbitKS': RelativeEquilibriumOrbitKS}
    return class_dict


def _orbit_instantiation(f, class_generator, data_format='orbithunter', **orbitkwargs):
    if data_format == 'orbithunter':
        field = np.array(f['field'])
        params = tuple(f['parameters'])
        orbit_ = class_generator(state=field, basis='field', parameters=params, **orbitkwargs)
    elif data_format == 'orbithunter_old':
        field = np.array(f['field'])
        L = float(f['space_period'][()])
        T = float(f['time_period'][()])
        S = float(f['spatial_shift'][()])
        orbit_ = class_generator(state=field, basis='field', parameters=(T, L, S), **orbitkwargs)
    else:
        fieldtmp = f['/data/ufield']
        L = float(f['/data/space'][0])
        T = float(f['/data/time'][0])
        field = fieldtmp[:]
        S = float(f['/data/shift'][0])
        orbit_ = class_generator(state=field, basis='field', parameters=(T, L, S), **orbitkwargs)
    return orbit_


def ks_parsing_util():
    return _parsing_dictionary(), _orbit_instantiation