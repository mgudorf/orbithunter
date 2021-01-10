from math import pi
from .arrayops import *
from ..core import Orbit
from scipy.fft import rfft, irfft
from scipy.linalg import block_diag
from mpl_toolkits.axes_grid1 import make_axes_locatable
import os
import numpy as np
import matplotlib.pyplot as plt

__all__ = ['OrbitKS', 'RelativeOrbitKS', 'ShiftReflectionOrbitKS', 'AntisymmetricOrbitKS', 'EquilibriumOrbitKS',
           'RelativeEquilibriumOrbitKS']


class OrbitKS(Orbit):

    def __init__(self, state=None, basis=None, parameters=None, **kwargs):
        """ Object that represents invariant 2-torus approximation for the Kuramoto-Sivashinsky equation.

        Parameters
        ----------
        state : ndarray(dtype=float, ndim=2), default None
            Array which contains one of the following: velocity field,
            spatial Fourier modes, or spatiotemporal Fourier modes; should match the 'basis' keyword.
            If None then a randomly generated set of spatiotemporal modes will be produced.
        basis : str, default None
            Which basis the array 'state' is currently in. Takes values
            'field', 'spatial_modes', 'modes'.
        parameters : tuple, default None
            Time period, spatial period, spatial shift (unused but kept for uniformity, in case of conversion between
            OrbitKS and RelativeOrbitKS).
        **kwargs :
            Extra arguments for _parse_parameters and _parse_state

        See Also
        --------
        Thesis: https://github.com/mgudorf/orbithunter/blob/master/docs/spatiotemporal_tiling_of_the_KSe.pdf

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

        The philosophy behind initializing the state, instead of leaving it empty is to avoid setting attributes
        after the init process. I cannot think of a situation where you would want an instance without a state AND
        want to perform the types of calculations possible with orbithunter; as you would have to specify
        dimensions of the state in either case.
        """
        super().__init__(state=state, basis=basis, parameters=parameters, **kwargs)

    def state_vector(self):
        """ Vector which completely specifies the orbit, contains state information and parameters. """
        return np.concatenate((self.state.reshape(-1, 1),
                               np.array([[float(self.t)]]),
                               np.array([[float(self.x)]])), axis=0)

    def statemul(self, other):
        """ Elementwise multiplication of two Orbits states

        Parameters
        ----------
        other : Orbit instance
            Second component of the state multiplication

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

    def transform(self, to='modes'):
        """ Convert current state to a different basis.

        Parameters
        ----------
        to : str
            One of the following: 'field', 'spatial_modes', 'modes'. Specifies the basis which the orbit will be converted to.

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
        This method is just a wrapper for different Fourier transforms. It's purpose is to remove the
        need for the user to keep track of the basis by hand. This should be used as opposed to Fourier transforms.
        """
        if self.state is None:
            raise ValueError('Trying to transform an unpopulated {} instance.'.format(str(self)))
        elif self.basis is None:
            raise ValueError('Trying to transform state with unknown basis'.format(str(self)))

        if to == 'field':
            if self.basis == 'spatial_modes':
                return self._inv_space_transform()
            elif self.basis == 'modes':
                return self._inv_spacetime_transform()
            else:
                return self
        elif to == 'spatial_modes':
            if self.basis == 'field':
                return self._space_transform()
            elif self.basis == 'modes':
                return self._inv_time_transform()
            else:
                return self
        elif to == 'modes':
            if self.basis == 'spatial_modes':
                return self._time_transform()
            elif self.basis == 'field':
                return self._spacetime_transform()
            else:
                return self
        else:
            raise ValueError('Trying to transform to unrecognized basis.')

    def dt(self, order=1, return_array=False):
        """ Time derivatives of the current state.

        Parameters
        ----------
        order :int
            The order of the derivative.
        return_array : bool
            Whether or not to return a numpy array. Used for efficiency/avoiding construction of redundant
            Orbit instances.

        Returns
        ----------
        orbit_dtn : OrbitKS or subclass instance
            The class instance whose state is the time derivative in
            the spatiotemporal mode basis.
        """
        # Need mode basis to compute derivatives
        modes = self.transform(to='modes').state
        # Elementwise multiplication of modes with frequencies, this is the derivative.
        dtn_modes = np.multiply(elementwise_dtn(self.t, self.n, self.shapes()[2][1], order=order), modes)

        # If the order of the derivative is odd, then imaginary component and real components switch.
        if np.mod(order, 2):
            dtn_modes = swap_modes(dtn_modes, axis=0)
        # To avoid redundant instantiation of instances, can return ndarray instead.
        if return_array:
            return dtn_modes
        else:
            # return the derivative in an instance
            orbit_dtn = self.__class__(state=dtn_modes, basis='modes', parameters=self.parameters)
            return orbit_dtn.transform(to=self.basis)

    def dx(self, order=1, computation_basis='modes', return_array=False, **kwargs):
        """ Spatial derivative of the current state.

        Parameters
        ----------
        order :int
            The order of the derivative.
        computation_basis : str
            The basis in which to perform the tensor products
        return_array : bool
            Whether to return a numpy array or Orbit instance, primarily for internal use.
        Returns
        ----------
        orbit_dxn : OrbitKS or subclass instance
            Class instance whose spatiotemporal state represents the spatial derivative in the
            the basis of the original state.

        Notes
        -----
        For agility, differentiation will silently perform Fourier transforms to get into the "right" basis in
        which to compute the tensor products. The onus of responsibility is put on the user to transform their
        instances prior to differentiation. In cases where forgetting to do so would cause dramatic slow downs,
        i.e. optimization, errors are raised.

        The general case returned by the function elementwise_dxn is an array of spatial frequencies of the shape
        [N-1, M-2]. The columns are comprised of two repeats of an array of dimension [N-1, M//2-1]; for orbits
        with discrete symmetry, we only want this array for the differentiation in the mode basis, simply due
        to how the selection rules work. Therefore, we can slice by the shape of the mode tensor; for orbits without
        discrete symmetry this does nothing, for those with discrete symmetry, it slices the half that we want.

        """
        if computation_basis == 'spatial_modes':
            # can compute spatial derivative in spatial mode or spatiotemporal mode basis.
            modes = self.transform(to='spatial_modes').state
            # Elementwise multiplication of modes with frequencies, this is the derivative.
            dxn_modes = np.multiply(elementwise_dxn(self.x, self.m, self.shapes()[1][0],
                                                    order=order), modes)
        else:
            modes = self.transform(to='modes').state
            dxn_modes = np.multiply(elementwise_dxn(self.x, self.m, self.shapes()[2][0],
                                                    order=order)[:, :self.shapes()[2][1]], modes)
        # If the order of the differentiation is odd, need to swap imaginary and real components.
        if np.mod(order, 2):
            dxn_modes = swap_modes(dxn_modes, axis=1)

        if return_array:
            return dxn_modes
        else:
            orbit_dxn = self.__class__(state=dxn_modes, basis=computation_basis, parameters=self.parameters)
            return orbit_dxn.transform(to=kwargs.get('return_basis', self.basis))

    def dae(self, **kwargs):
        """ Instance whose state is the Kuramoto-Sivashinsky equation evaluated at the current state

        kwargs :
            Unused, to match signature of Orbit

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is the spatiotamporal fourier modes resulting from the calculation of the K-S equation:
            OrbitKS.state = u_t + u_xx + u_xxxx + 1/2 (u^2)_x
        """
        # to be efficient, should be in modes basis.
        assert self.basis == 'modes', 'Convert to spatiotemporal Fourier mode basis before computing K-S equation DAEs.'

        # to avoid two IFFT calls, convert before nonlinear product
        orbit_field = self.transform(to='field')

        # Compute the Kuramoto-sivashinsky equation
        mapping_modes = (self.dt(return_array=True) + self.dx(order=2, return_array=True)
                         + self.dx(order=4, return_array=True)
                         + orbit_field.nonlinear(orbit_field, return_array=True))
        return self.__class__(state=mapping_modes, basis='modes', parameters=self.parameters)

    def nonlinear(self, other, return_array=False):
        """ Computation of the nonlinear term of the Kuramoto-Sivashinsky equation

        Parameters
        ----------

        other : OrbitKS
            The second component of the nonlinear product.
        return_array : bool
            Whether to return a numpy array or Orbit instance, primarily for internal use.
        Notes
        -----
        The nonlinear product is the name given to the elementwise product in the field basis equivalent to the
        convolution of spatiotemporal Fourier modes, the defining quality of a pseudospectral implementation.
        The matrix vector product takes the form d_x (u * v), but the "normal" usage is d_x (u * u); in the latter
        case 'other' should equal 'self', in the field basis.

        """
        # Elementwise product, both self and other should be in physical field basis.
        assert (self.basis == 'field') and (other.basis == 'field')
        return 0.5 * self.statemul(other).dx(return_array=return_array)

    def rnonlinear(self, other, return_array=False):
        """ Computation of the nonlinear term of the adjoint Kuramoto-Sivashinsky equation

        Parameters
        ----------
        other : OrbitKS
            The second component of the nonlinear product
        return_array : bool
            If True then return ndarray instead of instance.

        Notes
        -----
        The matrix-vector product comprised of adjoint Jacobian evaluated at 'self'
        multiplied with the spatiotemporal modes from another orbit instance (typically the DAE modes)
        Elementwise/vectorized operation takes the form -u * v_x.

        """
        assert self.basis == 'field'
        if return_array:
            # cannot return modes from derivative immediately because it needs to be
            # a class instance so IFFT can be applied.
            return -1.0 * self.statemul(other.dx().transform(to='field')).transform(to='modes').state
        else:
            return -1.0 * self.statemul(other.dx().transform(to='field')).transform(to='modes')

    def jacobian(self, **kwargs):
        """ Jacobian matrix evaluated at the current state.

        kwargs :
            Unused, included to match signature in Orbit class.

        Returns
        -------
        jac_ : 2-d ndarray
            Has dimensions dependent on number of spatiotemporal modes and free parameters,
            (self.shapes()[-1], self.shapes()[-1].size + n_params)
            Jacobian matrix of the KSe where n_params = 2 - sum(parameter_constraints)
        """
        # The Jacobian components for the spatiotemporal Fourier modes
        jac_ = self._jac_lin() + self._jac_nonlin()
        # Augment the jacobian with the partial derivatives with respect to parameters.
        jac_ = self._jacobian_parameter_derivatives_concat(jac_)
        return jac_

    def matvec(self, other, **kwargs):
        """ Matrix-vector product of a vector with the Jacobian of the current state.

        Parameters
        ----------
        other : OrbitKS
            OrbitKS instance whose state represents the vector in the matrix-vector multiplication.

        kwargs : dict
            Included to match Orbit signature

        Returns
        -------
        OrbitKS :
            OrbitKS whose state and other parameters result from the matrix-vector product.

        Notes
        -----
        Equivalent to computation of v_t + v_xx + v_xxxx + d_x (u .* v), where v is the state of 'other'.
        """

        assert (self.basis == 'modes') and (other.basis == 'modes')
        self_field = self.transform(to='field')
        # The correct derivative of the vector in the matrix vector product needs the current state parameters;
        # not the parameters stored in other;
        other_mode_component = other.__class__(state=other.state, parameters=self.parameters)
        other_field = other_mode_component.transform(to='field')

        # Factor of two corrects the 1/2 u^2 from differentiation of nonlinear term.
        matvec_modes = (other_mode_component.dt(return_array=True) + other_mode_component.dx(order=2, return_array=True)
                        + other_mode_component.dx(order=4, return_array=True)
                        + 2 * self_field.nonlinear(other_field, return_array=True))

        if not self.constraints['t']:
            # Compute the product of the partial derivative with respect to T with the vector's value of T.
            # This is typically an incremental value dT.
            matvec_modes += other.parameters[0] * (-1.0 / self.t) * self.dt(return_array=True)

        if not self.constraints['x']:
            # Compute the product of the partial derivative with respect to L with the vector's value of L.
            # This is typically an incremental value dL.
            dfdl = ((-2.0/self.x)*self.dx(order=2, return_array=True)
                    + (-4.0/self.x)*self.dx(order=4, return_array=True)
                    + (-1.0/self.x) * self_field.nonlinear(self_field, return_array=True))
            matvec_modes += other.parameters[1] * dfdl

        return self.__class__(state=matvec_modes, basis='modes', parameters=self.parameters)

    def rmatvec(self, other, **kwargs):
        """ Matrix-vector product with the adjoint of the Jacobian

        Parameters
        ----------
        other : OrbitKS
            OrbitKS whose state represents the vector in the matrix-vector product.

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
        # store the state in the field basis for the pseudospectral products
        self_field = self.transform(to='field')
        rmatvec_modes = (-1.0 * other.dt(return_array=True) + other.dx(order=2, return_array=True)
                         + other.dx(order=4, return_array=True)
                         + self_field.rnonlinear(other, return_array=True))

        # parameters are derived by multiplying partial derivatives w.r.t. parameters with the other orbit.
        rmatvec_params = self.rmatvec_parameters(self_field, other)

        return self.__class__(state=rmatvec_modes, basis='modes', parameters=rmatvec_params)

    def rmatvec_parameters(self, self_field, other):
        """ Parameter values from product with partial derivatives

        Parameters
        ----------
        self_field : OrbitKS
            The orbit in the field basis; this cuts down on redundant transforms.
        other : OrbitKS
            The adjoint/co-state variable Orbit instance.

        Returns
        -------
        parameters : tuple
            Set of parameters resulting from the last rows of the product with adjoint Jacobian.
        """
        other_modes_in_vector_form = other.state.ravel()
        if not self.constraints['t']:
            # partial derivative with respect to period times the adjoint/co-state variable state.
            rmatvec_T = (-1.0 / self.t) * self.dt(return_array=True).ravel().dot(other_modes_in_vector_form)
        else:
            rmatvec_T = 0

        if not self.constraints['x']:
            # change in L, dL, equal to DF/DL * v
            # original
            rmatvec_L = ((-2.0 / self.x) * self.dx(order=2, return_array=True)
                         + (-4.0 / self.x) * self.dx(order=4, return_array=True)
                         + (-1.0 / self.x) * self_field.nonlinear(self_field, return_array=True)
                         ).ravel().dot(other_modes_in_vector_form)
        else:
            rmatvec_L = 0

        return rmatvec_T, rmatvec_L, 0.

    def cost_function_gradient(self, dae, **kwargs):
        """ Derivative of 1/2 |F|^2

        Parameters
        ----------
        dae : OrbitKS
            Orbit instance whose state equals DAE evaluated with respect to current state, i.e. F(v)
        kwargs

        Returns
        -------
        gradient :
            Orbit instance whose state contains (dF/dv)^T * F  = J^T F; (adjoint Jacobian * DAE)

        Notes
        -----
        This takes DAE as an argument because it would otherwise result in redundant calculations in some optimize
        methods.
        """
        preconditioning = kwargs.get('preconditioning', False)
        if preconditioning:
            # This preconditions with respect to the current state. not J^T F
            gradient = (self.rmatvec(dae, **kwargs)
                        ).precondition(pmult=self.preconditioning_parameters)
        else:
            gradient = self.rmatvec(dae, **kwargs)
        return gradient

    def increment(self, other, step_size=1, **kwargs):
        """ Add optimization correction to current state.

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

    def plot(self, show=True, save=False, fundamental_domain=False, **kwargs):
        """ Plot the velocity field as a 2-d density plot using matplotlib's imshow

        Parameters
        ----------
        show : bool
            Whether or not to display the figure
        save : bool
            Whether to save the figure
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
        if np.product(self.discretization) >= 256**2:
            padding = kwargs.get('padding', False)
        else:
            padding = kwargs.get('padding', True)
        plt.rc('text', usetex=True)
        plt.rc('font', family='serif')
        plt.rcParams['text.usetex'] = True

        if padding:
            padding_shape = kwargs.get('padding_shape', (16*self.n, 16*self.m))
            plot_orbit = self.resize(padding_shape)
        else:
            plot_orbit = self.copy()

        if fundamental_domain:
            plot_orbit = plot_orbit.to_fundamental_domain().transform(to='field')
        else:
            # The fundamental domain is never used in computation, so no operations are required if we do not want
            # to plot the fundamental domain explicitly.
            plot_orbit = plot_orbit.transform(to='field')

        # The following creates custom tick labels and accounts for some pathological cases
        # where the period is too small (only a single label) or too large (many labels, overlapping due
        # to font size) Default label tick size is 10 for time and the fundamental frequency, 2 pi sqrt(2) for space.

        # Create time ticks, with the separation
        if plot_orbit.T > 10:
            timetick_step = np.max([np.min([100, (5 * 2**(np.max([int(np.log2(plot_orbit.T//2)) - 3,  1])))]), 5])
            yticks = np.arange(0, plot_orbit.T, timetick_step)
            ylabels = np.array([str(int(y)) for y in yticks])
        elif 0 < plot_orbit.T <= 10:
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
            xlabels = [str((xmult*x) // xscale) for x in xticks]
        else:
            scaled_L = np.round(plot_orbit.L / (2*pi*np.sqrt(2)), 1)
            xticks = np.array([0, plot_orbit.L])
            xlabels = np.array(['0', str(scaled_L)])

        default_figsize = (min([max([0.25, 0.15*plot_orbit.L**0.7]), 20]),
                           min([max([0.25, 0.15*plot_orbit.T**0.7]), 20]))

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
                filename = self.filename(extension=extension)
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

            if kwargs.get('verbose', False):
                print('Saving figure to {}'.format(filename))
            plt.savefig(filename, bbox_inches='tight', pad_inches=0.05)

        if show:
            plt.show()

        plt.close()
        return None

    def mode_plot(self, show=True, save=False, scale='log', **kwargs):
        """ Plot the mode values  as a 2-d density plot using matplotlib's imshow

        Parameters
        ----------
        show : bool
            Whether or not to display the figure
        save : bool
            Whether to save the figure
        scale : str
            Whether or not to plot using transformation of log10(|u|)
        **kwargs :
            filename : str
                The (custom) save name of the figure, if save==True. Save name will be generated otherwise.
            directory : str
                The location to save to, if save==True
        """
        plt.rc('text', usetex=True)
        plt.rc('font', family='serif')
        plt.rcParams['text.usetex'] = True

        if scale == 'log':
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

        filename = kwargs.get('filename', None)
        if save or (filename is not None):
            extension = kwargs.get('extension', '.png')
            directory = kwargs.get('directory', 'local')
            # Create save name if one doesn't exist.
            if filename is None:
                filename = self.filename(extension=extension)
            elif filename.endswith('.h5'):
                filename = filename.split('.h5')[0] + extension

            # Create save directory if one doesn't exist.
            if isinstance(directory, str):
                if directory == 'local':
                    directory = os.path.abspath(os.path.join(__file__, '../../../data/local/', str(self)))

            # If filename is provided as an absolute path it overrides the value of 'directory'.
            filename = os.path.abspath(os.path.join(directory, filename))

            if kwargs.get('verbose', False):
                print('Saving figure to {}'.format(filename))
            plt.savefig(filename, bbox_inches='tight', pad_inches=0.05)

        if show:
            plt.show()

        plt.close()
        return None

    def norm(self, ord=None):
        """ Norm of spatiotemporal state via numpy.linalg.norm

        Example
        -------
        L_2 distance between two states
        """
        return np.linalg.norm(self.state.ravel(), ord=ord)

    def preconditioning_parameters(self):
        """ Defining parameters; T, L, S kept for convenience"""
        return (self.t, self.n, self.shapes()[2][1]), (self.x, self.m, self.shapes()[2][0])

    def precondition(self, **kwargs):
        """ Precondition a vector with the inverse (absolute value) of linear spatial terms

        Parameters
        ----------
        kwargs :
            pmult : tuple of tuples
                Parameters returned by preconditioning parameters
            pexp : tuple
                Exponents for the parameter scaling

        Returns
        -------
        target : OrbitKS
            Return the OrbitKS instance, whose state and parameters have been modified by preconditioning.

        Notes
        -----
        Often we want to precondition a state derived from a mapping or rmatvec (gradient descent step),
        with respect to another orbit's (current state's) parameters. By passing parameters we can access the
        cached classmethods.

        I never preconditioned the spatial shift for relative periodic solutions so I don't include it here.
        """
        pmult = kwargs.get('pmult', self.preconditioning_parameters())
        p_multipliers = 1.0 / (np.abs(elementwise_dtn(*pmult[0]))
                               + np.abs(elementwise_dxn(*pmult[1], order=2))
                               + elementwise_dxn(*pmult[1], order=4))

        preconditioned_state = np.multiply(self.state, p_multipliers)
        # Precondition the change in T and L
        param_powers = kwargs.get('pexp', (1, 4))
        if not self.constraints['t']:
            # self is the orbit being preconditioned, i.e. the correction orbit; by default this is dT = dT / T
            T = self.t * (pmult[0][0]**-param_powers[0])
        else:
            T = self.t

        if not self.constraints['x']:
            # self is the orbit being preconditioned, i.e. the correction orbit; by default this is dL = dL / L^4
            L = self.x * (pmult[1][0]**-param_powers[1])
        else:
            L = self.x

        return self.__class__(state=preconditioned_state, parameters=(T, L, self.s), basis='modes')

    def rescale(self, magnitude=3., method='absolute'):
        """ Scalar multiplication

        Parameters
        ----------
        magnitude : float
            Scalar value which controls rescaling based on method.
        method : str
            power or absolute; absolute rescales the L_infty norm to a value equal to magnitude; power simply
            uses a power law rescaling.

        Returns
        -------
        OrbitKS
            rescaled Orbit instance
        """

        field = self.transform(to='field').state
        if method == 'absolute':
            rescaled_field = ((magnitude * field) / np.max(np.abs(field.ravel())))
        elif method == 'power':
            rescaled_field = np.sign(field) * np.abs(field)**magnitude
        else:
            raise ValueError('Unrecognizable method.')
        return self.__class__(state=rescaled_field, basis='field',
                              parameters=self.parameters).transform(to=self.basis)

    def reflection(self):
        """ Reflect the velocity field about the spatial midpoint

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is the reflected velocity field -u(L-x,t).
        """
        # Different points in space represented by columns of the state array
        reflected_field = -1.0*np.roll(np.fliplr(self.transform(to='field').state), 1, axis=1)
        return self.__class__(state=reflected_field, basis='field',
                              parameters=(self.t, self.x, -1.0*self.s)).transform(to=self.basis)

    def rotate(self, distance, axis=0, units='plotting'):
        """ Rotate the velocity field in either space or time.

        Parameters
        ----------
        distance : float
            The rotation / translation amount, in dimensionless units of time or space.
        axis : int
            The axis of the ndarray (state) that will be padded.
        units : str
            Determines the spatial units of the provided rotation

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
            thetak = distance * temporal_frequencies(self.t, self.n, order=1)
            cosinek = np.cos(thetak)
            sinek = np.sin(thetak)

            orbit_to_rotate = self.transform(to='modes')
            # Refer to rotation matrix in 2-D for reference.
            cosine_block = np.tile(cosinek.reshape(-1, 1), (1, orbit_to_rotate.shapes()[2][1]))
            sine_block = np.tile(sinek.reshape(-1, 1), (1, orbit_to_rotate.shapes()[2][1]))

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
            thetak = distance * spatial_frequencies(self.x, self.m, order=1)
            cosinek = np.cos(thetak)
            sinek = np.sin(thetak)

            orbit_to_rotate = self.transform(to='spatial_modes')
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
            rotated_spatial_modes = np.concatenate((rotated_real, rotated_imag), axis=1)

            return self.__class__(state=rotated_spatial_modes, basis='spatial_modes',
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
        shift_reflected_field = np.roll(-1.0*np.roll(np.fliplr(self.transform(to='field').state),
                                                     1, axis=1), self.n // 2, axis=0)
        return self.__class__(state=shift_reflected_field, basis='field',
                              parameters=self.parameters).transform(to=self.basis)

    def cell_shift(self, n_cell, axis=0):
        """ Rotate by period/n_cell in either axis.

        Parameters
        ----------
        n_cell : integer
            Orbit field being shifted by amount dimension / n_cell
        axis :
            Axis

        Returns
        -------

        """
        return self.roll(np.sign(n_cell)*self.discretization[axis] // np.abs(n_cell), axis=axis)

    def roll(self, shift, axis=0):
        """ Apply numpy roll along specified axis.

        Parameters
        ----------
        shift : int
            Number of collocation points (discrete rotations) to rotate by
        axis : int
            The numpy ndarray along which to roll

        Returns
        -------
        Orbit :
            Instance with rolled state
        """
        field = self.transform(to='field').state
        return self.__class__(state=np.roll(field, shift, axis=axis), basis='field',
                              parameters=self.parameters).transform(to=self.basis)

    def group_orbit(self, **kwargs):
        """ Returns a generator of the orbit's group orbit

        Returns
        -------

        """
        if kwargs.get('discrete_only', False):
            # The discrete symmetry operations which preserve reflection symmetry axis.
            for g in (self, self.reflection(), self.cell_shift(2, axis=1), self.cell_shift(2, axis=1).reflection()):
                yield g.to_fundamental_domain()
        else:
            # Don't need cell shifts, these are within the rotations.
            strides = kwargs.get('strides', (1, 1))
            for g in [self, self.reflection()]:
                for N in range(0, g.shapes()[0][0], strides[0]):
                    for M in range(0, g.shapes()[0][1], strides[1]):
                        yield g.roll(N, axis=0).roll(M, axis=1).to_fundamental_domain()

    def shapes(self):
        """ State array shapes in different bases. See core.py for details.
        """
        return (self.n, self.m), (self.n, self.m - 2), (max([self.n-1, 1]), self.m-2)

    def dimensions(self):
        """ Tile dimensions. """
        return self.t, self.x

    def plotting_dimensions(self):
        """ Dimensions according to plot labels; used in clipping. """
        return (0., self.t), (0., self.x / (2 * pi * np.sqrt(2)))

    @classmethod
    def parameter_based_discretization(cls, dimensions, **kwargs):
        """ Follow orbithunter conventions for discretization size.

        Parameters
        ----------
        dimensions : tuple
            tuple containing (T, L) as first two entries of tuple (i.e. self.parameters or self.dimensions)

        kwargs :
            default : str
            Takes values 'coarse', 'normal', 'fine', 'power'.
            These options return the according discretization sizes as described below.

        Returns
        -------
        N, M : tuple of ints
            The new spatiotemporal field discretization; number of time points
            (rows) and number of space points (columns)

        Notes
        -----
        This function should only ever be called by resize, the returned values can always be accessed by
        the appropriate attributes of the rediscretized orbit.
        """
        resolution = kwargs.get('resolution', 'default')
        T, L = dimensions
        N, M = kwargs.get('N', None), kwargs.get('M', None)
        if N is None:
            if T in [0, 0.]:
                N = 32
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

        if M is None:
            if L in [0, 0.]:
                M = 32
            elif isinstance(resolution, tuple):
                M = np.max([2**(int(np.log2(L)+resolution[1])), 16])
            elif resolution == 'coarse':
                M = np.max([2**(int(np.log2(L)-1)), 16])
            elif resolution == 'fine':
                M = np.max([2**(int(np.log2(L)+2)), 32])
            elif resolution == 'power':
                M = np.max([2*(int(4*L**(1./2.))//2), 32])
            else:
                M = np.max([2**(int(np.log2(L)+0.5)), 32])

        return N, M

    def copy(self):
        """ Create another Orbit instance with a copied state array"""
        return self.__class__(state=self.state.copy(), basis=self.basis, parameters=self.parameters)

    def dot(self, other):
        """ Return the L_2 inner product of two orbits

        Returns
        -------
        float :
            The value of self * other via L_2 inner product.
        """
        return float(np.dot(self.state.ravel(), other.state.ravel()))

    def pad(self, size, axis=0):
        """ Increase the size of the discretization via zero-padding

        Parameters
        ----------
        size : int
            The new size of the discretization, must be an even integer
            larger than the current size of the discretization (handled by resize method).

        axis : int
            The dimension of the state that will be padded.

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
                padding = (size-modes.N) // 2
                padding_tuple = ((padding, padding), (0, 0))
                padded_modes = np.concatenate((modes.state[:-modes.n, :],
                                               np.pad(modes.state[-modes.n:, :], padding_tuple)), axis=0)
                padded_modes *= np.sqrt(size / modes.N)
            else:
                padding = (size-modes.M) // 2
                padding_tuple = ((0, 0), (padding, padding))
                padded_modes = np.concatenate((modes.state[:, :-modes.m],
                                               np.pad(modes.state[:, -modes.m:], padding_tuple)), axis=1)
                padded_modes *= np.sqrt(size / modes.M)
        return self.__class__(state=padded_modes, basis='modes',
                              parameters=self.parameters).transform(to=self.basis)

    def truncate(self, size, axis=0):
        """ Decrease the size of the discretization via truncation

        Parameters
        ----------
        size : int
            The new size of the discretization, must be an even integer
            smaller than the current size of the discretization (handled by resize method).

        axis : int
            The dimension of the state that will be padded.

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
                truncate_number = int(size // 2) - 1
                # Split into real and imaginary components, truncate separately.
                first_half = modes.state[:truncate_number+1, :]
                second_half = modes.state[-modes.n:-modes.n+truncate_number, :]
                truncated_modes = np.sqrt(size / modes.N) * np.concatenate((first_half, second_half), axis=0)
            else:
                truncate_number = int(size // 2) - 1
                # Split into real and imaginary components, truncate separately.
                first_half = self.state[:, :truncate_number]
                second_half = self.state[:, -(int(self.m // 2) - 1):-(int(self.m // 2) - 1) + truncate_number]
                truncated_modes = np.sqrt(size / modes.M) * np.concatenate((first_half, second_half), axis=1)
        return self.__class__(state=truncated_modes, basis=self.basis, parameters=self.parameters)

    def verify_integrity(self):
        """ Check whether the orbit converged to an equilibrium or close-to-zero solution
        """
        # Take the L_2 norm of the field, if uniformly close to zero, the magnitude will be very small.
        field_orbit = self.transform(to='field')

        # See if the L_2 norm is beneath a threshold value, if so, replace with zeros.
        if field_orbit.norm() < 10**-5:
            code = 4
            return EquilibriumOrbitKS(state=np.zeros([self.n, self.m]), basis='field',
                                      parameters=self.parameters).transform(to=self.basis), code
        # Equilibrium is defined by having no temporal variation, i.e. time derivative is a uniformly zero.
        elif self.t in [0., 0]:
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

    @staticmethod
    def default_shape():
        """ The shape of a generic state, not based on any dimensions.

        Returns
        -------
        tuple of int :
            The default array shape when dimensions are not specified.

        Notes
        -----
        32 x 32 is used because this is the shape that generally works for small tile sizes.
        """
        return 32, 32

    @staticmethod
    def bases():
        """ Labels of the different bases generated by different transforms.

        Notes
        -----

        """
        return 'field', 'spatial_modes', 'modes'

    @staticmethod
    def dimension_labels():
        """ Labels of the tile dimensions, time and space periods.

        Notes
        -----
        This seems redundant in the context of parameter_labels staticmethod. It is used in the spatiotemporal
        techniques for readability and also for generalization to other equations.
        """
        return 't', 'x'

    @staticmethod
    def parameter_labels():
        """ Labels of all parameters."""
        return 't', 'x', 's'

    @staticmethod
    def discretization_labels():
        """ Strings to use to label dimensions/periods. Generic 3+1 spacetime labels default.
        """
        return 'n', 'm'

    def to_h5(self, filename=None, orbit_name=None, h5py_mode='a', verbose=False, include_residual=True):
        """ Export current state information to HDF5 file. See core.py for more details

        Parameters
        ----------
        filename
        orbit_name
        h5py_mode
        verbose
        include_residual

        Notes
        -----
        Mainly an overload simply to get a different default behavior for include_residual.
        """
        super().to_h5(filename=filename, orbit_name=orbit_name, h5py_mode=h5py_mode, verbose=verbose,
                      include_residual=include_residual)

    def _generate_state(self, **kwargs):
        """ Initial a set of random spatiotemporal Fourier modes
        Parameters
        ----------
        parameters : tuple of floats

        **kwargs
            tscale : int
                The number of temporal frequencies to keep after truncation.
            xscale : int
                The number of spatial frequencies to get after truncation.
            xvar : float
                Plays the role of variance for Gaussian and GTES scaling
            tvar : float
                Plays the role of variance for Gaussian and GTES scaling
            seed
        Returns
        -------
        self :
            OrbitKS whose state has been modified to be a set of random Fourier modes.
        Notes
        -----
        These are the initial condition generators that I find the most useful. If a different method is
        desired, simply pass the array as 'state' variable to __init__.

        By initializing the shape parameters and orbit parameters, the other properties get initialized, so
        they can be referenced in what follows (). I am unsure whether or not
        this is bad practice but they could be replaced by the corresponding tuples. The reason why this is avoided
        is so this function generalizes to subclasses.
        """
        # TODO : refactor the subclass random_states
        spectrum = kwargs.get('spectrum', 'gtes')
        tscale = kwargs.get('tscale', int(np.round(self.t / 25.)))
        xscale = kwargs.get('xscale', int(1 + np.round(self.x / (2*pi*np.sqrt(2)))))
        xvar = kwargs.get('xvar', np.sqrt(max([xscale, 1])))
        tvar = kwargs.get('tvar', np.sqrt(max([tscale, 1])))
        np.random.seed(kwargs.get('seed', None))

        # also accepts N and M as kwargs
        n, m = self.parameter_based_discretization(self.dimensions(), **kwargs)
        # self.n, (int(self.m // 2) - 1) = int(self.n // 2) - 1, int(self.m // 2) - 1

        # I think this is the easiest way to get symmetry-dependent Fourier mode arrays' shapes.
        # power = 2 b.c. odd powers not defined for spacetime modes for discrete symmetries.
        space_ = np.abs(elementwise_dxn(2*pi, self.m, self.shapes()[2][0])[:, :self.shapes()[2][1]]).astype(int)
        time_ = np.abs(elementwise_dtn(2*pi, self.n, self.shapes()[2][1])).astype(int)
        random_modes = np.random.randn(*self.shapes()[2])

        # Pretruncation norm, random normal distribution for modes approximately gives field of "correct" magnitude
        original_mode_norm = np.linalg.norm(random_modes)

        if spectrum == 'gaussian':
            # spacetime gaussian modulation
            gaussian_modulator = np.exp(-((space_ - xscale)**2/(2*xvar)) - ((time_ - tscale)**2 / (2*tvar)))
            modes = np.multiply(gaussian_modulator, random_modes)

        elif spectrum == 'gtes':
            gtime_espace_modulator = np.exp(-1.0 * ((np.abs(space_ - xscale) / np.sqrt(xvar))
                                            + ((time_ - tscale)**2 / (2*tvar))))
            modes = np.multiply(gtime_espace_modulator, random_modes)

        elif spectrum == 'exponential':
            # exponential decrease away from selected spatial scale
            truncate_indices = np.where(time_ > tscale)
            untruncated_indices = np.where(time_ <= tscale)
            time_[truncate_indices] = 0
            time_[untruncated_indices] = 1.
            exp_modulator = np.exp(-1.0 * np.abs(space_ - xscale) / xvar)
            exp_modulator = np.multiply(time_, exp_modulator)
            modes = np.multiply(exp_modulator, random_modes)

        elif spectrum == 'linear_exponential':
            # Modulate the spectrum using the spatial linear operator; equivalent to preconditioning.
            truncate_indices = np.where(time_ > tscale)
            untruncated_indices = np.where(time_ <= tscale)
            time_[truncate_indices] = 0
            time_[untruncated_indices] = 1.
            # so we get qk^2 - qk^4
            mollifier = -1.0*np.abs(((2*pi*xscale/self.x)**2-(2*pi*xscale/self.x)**4)
                                    - ((2*pi*space_ / self.x)**2+(2*pi*space_/self.x)**4))
            modulated_modes = np.multiply(np.exp(mollifier), random_modes)
            modes = np.multiply(time_, modulated_modes)

        elif spectrum == 'linear':
            # Modulate the spectrum using the spatial linear operator; equivalent to preconditioning.
            truncate_indices = np.where(time_ > tscale)
            untruncated_indices = np.where(time_ <= tscale)
            time_[truncate_indices] = 0
            time_[untruncated_indices] = 1.
            # so we get qk^2 - qk^4
            mollifier = np.abs(((2*pi*xscale/self.x)**2-(2*pi*xscale/self.x)**4))
            modulated_modes = np.divide(random_modes, np.exp(mollifier))
            modes = np.multiply(time_, modulated_modes)
        elif spectrum == 'plateau-linear':
            plateau = np.where(space_[space_ <= xscale])
            # so we get qk^2 - qk^4
            mollifier = (2*pi*space_/self.x)**2 - (2*pi*space_/self.x)**4
            mollifier[plateau] = 1
            modes = np.divide(random_modes, np.abs(mollifier))
        elif spectrum == 'plateau-exponential':
            # space scaling is constant up until certain wave number then exponential decrease
            # time scaling is static
            time_[time_ > tscale] = 0.
            time_[time_ != 0.] = 1.
            space_[space_ <= xscale] = xscale
            exp_modulator = np.exp(-1.0 * np.abs(space_ - xscale) / xvar)
            p_exp_modulator = np.multiply(time_, exp_modulator)
            modes = np.multiply(p_exp_modulator, random_modes)
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

        # Rescale
        self.state = (original_mode_norm / np.linalg.norm(modes)) * modes
        self.basis = 'modes'
        return None

    @classmethod
    def default_parameter_ranges(cls):
        return {'t': (20, 200), 'x': (20, 100), 's': (0, 0)}

    def _parse_state(self, state, basis, **kwargs):
        """ Instantiate state and infer shape of collocation grid from numpy array and basis
        """
        if isinstance(state, np.ndarray):
            self.state = state
        else:
            self.state = np.array([], dtype=float).reshape(0, 0)

        if self.size > 0:
            # This is essentially the inverse of .shapes() method
            if basis is None:
                raise ValueError('basis must be provided when state is provided')
            elif basis == 'modes':
                # N-1, M-2
                n, m = self.shape[0] + 1, self.shape[1] + 2
            elif basis == 'field':
                # N, M
                n, m = self.shape
            elif basis == 'spatial_modes':
                # N, M - 2
                n, m = self.shape[0], self.shape[1] + 2
            else:
                raise ValueError('basis parameter equal "field" or "spatial_modes", or "modes"')
            self.discretization = n, m
            self.basis = basis
        else:
            self.discretization = None
            # Don't use the basis value in case state is None but bad value used for basis
            self.basis = None

    def _jac_lin(self):
        """ The linear component of the Jacobian matrix of the Kuramoto-Sivashinsky equation"""
        return self._dt_matrix() + self._dx_matrix(order=2) + self._dx_matrix(order=4)

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
        jac_ : np.ndarray,
        np.product(self.shapes()[2])**2 dimensional array resultant from taking the derivative of the
        spatioatemporal mapping with respect to Fourier modes.
        Flags which indicate which parameters are constrained; if unconstrained then need to augment the Jacobian
        with partial derivatives with respect to unconstrained parameters.

        Returns
        -------
        Jacobian augmented with parameter partial derivatives as columns. Required to solve for changes to period,
        space period in optimization process. Makes the system rectangular; needs to be solved by least squares type
        methods.

        """
        # If period is not fixed, need to include dF/dT in jacobian matrix
        if not self.constraints['t']:
            time_period_derivative = (-1.0 / self.t)*self.dt(return_array=True).reshape(-1, 1)
            jac_ = np.concatenate((jac_, time_period_derivative), axis=1)

        # If spatial period is not fixed, need to include dF/dL in jacobian matrix
        if not self.constraints['x']:
            self_field = self.transform(to='field')
            spatial_period_derivative = ((-2.0 / self.x) * self.dx(order=2, return_array=True)
                                         + (-4.0 / self.x) * self.dx(order=4, return_array=True)
                                         + (-1.0 / self.x) * self_field.nonlinear(self_field, return_array=True))
            jac_ = np.concatenate((jac_, spatial_period_derivative.reshape(-1, 1)), axis=1)

        return jac_

    def _dx_matrix(self, order=1, computation_basis='modes'):
        """ The space derivative matrix operator for the current state.

        Parameters
        ----------
        order :int
            The order of the derivative.
        computation_basis : str
            The basis in which to produce the operator.
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
        # Coefficients which depend on the order of the derivative, see SO(2) generator of rotations for reference.
        if computation_basis == 'spatial_modes':
            # else use time discretization size.
            spacetime_dxn = np.kron(np.eye(self.n),  dxn_block(self.x, self.m, order=order))
        else:
            # When the dimensions of dxn_block are the same as the mode tensor, the slicing does nothing.
            # When the dimensions are smaller, i.e. orbits with discrete symmetries, then it will give non-sensical
            # results for odd ordered derivatives; however, odd ordered derivatives in the modes basis are not
            # well defined for these orbits anyway, hence, no contradiction is made.
            spacetime_dxn = np.kron(np.eye(self.shapes()[2][0]),
                                    dxn_block(self.x, self.m, order=order)[:self.shapes()[2][1], :self.shapes()[2][1]])

        return spacetime_dxn

    def _dt_matrix(self, order=1):
        """ The time derivative matrix operator for the current state.

        Parameters
        ----------
        order :int
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
        # Zeroth frequency was not included in frequency vector.
        dtn_matrix = block_diag([[0]], dtn_block(self.t, self.n, order=order))
        # Take kronecker product to account for the number of spatial modes.
        spacetime_dtn = np.kron(dtn_matrix, np.eye(self.shapes()[2][1]))
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

    def _time_transform(self, return_array=False):
        """ Temporal Fourier transform

        Parameters
        ----------
        return_array : bool
            Whether or not to return a numpy array. Used for efficiency/avoiding construction of redundant
            Orbit instances.
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
        if return_array:
            return spacetime_modes
        else:
            return self.__class__(state=spacetime_modes, basis='modes', parameters=self.parameters)

    def _inv_time_transform(self, return_array=False):
        """ Temporal Fourier transform

        Parameters
        ----------
        return_array : bool
            Whether or not to return a numpy array. Used for efficiency/avoiding construction of redundant
            Orbit instances.

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the temporal Fourier mode basis.

        """
        modes = self.state
        padding = np.zeros([1, modes.shape[1]])
        time_real = np.concatenate((modes[:-max([int(self.n // 2) - 1,  1]), :], padding), axis=0)
        time_imaginary = np.concatenate((padding, modes[-max([int(self.n // 2) - 1,  1]):, :], padding), axis=0)
        complex_modes = time_real + 1j * time_imaginary
        complex_modes[1:, :] *= (1./np.sqrt(2))
        space_modes = irfft(complex_modes, norm='ortho', axis=0)
        if return_array:
            return space_modes
        else:
            return self.__class__(state=space_modes, basis='spatial_modes', parameters=self.parameters)

    def _space_transform(self, return_array=False):
        """ Spatial Fourier transform

        Parameters
        ----------


        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        space_modes_complex = np.sqrt(2) * rfft(self.state, norm='ortho', axis=1)[:, 1:-1]
        spatial_modes = np.concatenate((space_modes_complex.real, space_modes_complex.imag), axis=1)
        if return_array:
            return spatial_modes
        else:
            return self.__class__(state=spatial_modes, basis='spatial_modes', parameters=self.parameters)

    def _inv_space_transform(self, return_array=False):
        """ Spatial Fourier transform

        Parameters
        ----------


        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Make the modes complex valued again.
        complex_modes = self.state[:, :-(int(self.m // 2) - 1)] + 1j * self.state[:, -(int(self.m // 2) - 1):]
        # Re-add the zeroth and Nyquist spatial frequency modes (zeros) and then transform back
        z = np.zeros([self.n, 1])
        field = (1./np.sqrt(2))*irfft(np.concatenate((z, complex_modes, z), axis=1), norm='ortho', axis=1)
        if return_array:
            return field
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
        dft_mat = rfft(np.eye(self.n), norm='ortho', axis=0)
        time_dft_mat = np.concatenate((dft_mat[:-1, :].real,
                                       dft_mat[1:-1, :].imag), axis=0)
        time_dft_mat[1:, :] = np.sqrt(2)*time_dft_mat[1:, :]
        return np.kron(time_dft_mat, np.eye(self.m-2))

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
        idft_mat_real = irfft(np.eye(self.n//2 + 1), norm='ortho', axis=0)
        idft_mat_imag = irfft(1j * np.eye(self.n//2 + 1), norm='ortho', axis=0)
        time_idft_mat = np.concatenate((idft_mat_real[:, :-1],
                                        idft_mat_imag[:, 1:-1]), axis=1)
        # to make the transformations orthogonal, based on scipy implementation of scipy.fft.irfft
        time_idft_mat[:, 1:] = time_idft_mat[:, 1:]/np.sqrt(2)
        return np.kron(time_idft_mat, np.eye(self.m-2))

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

        idft_mat_real = irfft(np.eye(self.m//2 + 1), norm='ortho', axis=0)[:, 1:-1]
        idft_mat_imag = irfft(1j*np.eye(self.m//2 + 1), norm='ortho', axis=0)[:, 1:-1]
        # to make the transformations orthogonal, based on scipy implementation of scipy.fft.irfft
        space_idft_mat = (1./np.sqrt(2)) * np.concatenate((idft_mat_real, idft_mat_imag), axis=1)
        return np.kron(np.eye(self.n), space_idft_mat)

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

        dft_mat = rfft(np.eye(self.m), norm='ortho', axis=0)[1:-1, :]
        space_dft_mat = np.sqrt(2) * np.concatenate((dft_mat.real, dft_mat.imag), axis=0)
        return np.kron(np.eye(self.n), space_dft_mat)

    def _inv_spacetime_transform(self, return_array=False):
        """ Inverse space-time Fourier transform

        Parameters
        ----------
        Returns
        -------
        OrbitKS :
            OrbitKS instance in the physical field basis.
        """
        if return_array:
            return self._inv_time_transform()._inv_space_transform().state
        else:
            return self._inv_time_transform()._inv_space_transform()

    def _spacetime_transform(self, return_array=False):
        """ Space-time Fourier transform

        Parameters
        ----------
        Returns
        -------
        OrbitKS :
            OrbitKS instance in the spatiotemporal mode basis.
        """
        if return_array:
            return self._space_transform()._time_transform().state
        else:
            # Return transform of field
            return self._space_transform()._time_transform()


class RelativeOrbitKS(OrbitKS):

    def __init__(self, state=None, basis=None, parameters=None, frame='comoving', **kwargs):
        # For uniform save format
        self.frame = frame
        super().__init__(state=state, basis=basis, parameters=parameters, **kwargs)

    def dt(self, order=1, return_array=False):
        """ A time derivative of the current state.

        Parameters
        ----------
        order :int
            The order of the derivative.
        return_array : bool
            Whether to return np.ndarray or Orbit instance

        Returns
        ----------
        orbit_dtn : OrbitKS or subclass instance
            The class instance whose state is the time derivative in
            the spatiotemporal mode basis.
        """
        if self.frame == 'comoving':
            return super().dt(order=order, return_array=return_array)
        else:
            raise ValueError(
                'Attempting to compute time derivative of '+str(self)+'in physical reference frame.')

    def dae(self, **kwargs):
        """ Extension of OrbitKS method to include co-moving frame term. """
        return super().dae() + self.comoving_mapping_component()

    def matvec(self, other, **kwargs):
        """ Extension of parent class method

        Parameters
        ----------
        other : RelativeOrbitKS
            RelativeOrbitKS instance whose state represents the vector in the matrix-vector multiplication.

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
        if not self.constraints['t']:
            matvec_comoving.state += other.T * (-1.0 / self.t) * (-self.s / self.t) * self_dx

        if not self.constraints['x']:
            # Derivative of mapping with respect to T is the same as -1/T * u_t
            matvec_comoving.state += other.L * (-1.0 / self.x) * (-self.s / self.t) * self_dx

        if not self.constraints['s']:
            # technically could do self_comoving / self.s but this can be numerically unstable when self.s is small
            matvec_comoving.state += other.S * (-1.0 / self.t) * self_dx

        return matvec_orbit + matvec_comoving

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

        if not self.constraints['t']:
            # Derivative with respect to T term equal to DF/DT * v
            rmatvec_T = (-1.0 / self.t) * (self.dt(return_array=True)
                                           + (-self.s / self.t) * self_dx_modes).ravel().dot(other_modes)
        else:
            rmatvec_T = 0

        if not self.constraints['x']:
            # change in L, dL, equal to DF/DL * v
            rmatvec_L = ((-2.0 / self.x) * self.dx(order=2, return_array=True)
                         + (-4.0 / self.x) * self.dx(order=4, return_array=True)
                         + (-1.0 / self.x) * (self_field.nonlinear(self_field, return_array=True)
                                              + (-self.s / self.t) * self_dx_modes)
                         ).ravel().dot(other_modes)

        else:
            rmatvec_L = 0

        if not self.constraints['s']:
            rmatvec_S = (-1.0 / self.t) * self_dx_modes.ravel().dot(other_modes)
        else:
            rmatvec_S = 0.

        return rmatvec_T, rmatvec_L, rmatvec_S

    def comoving_mapping_component(self, return_array=False):
        """ Co-moving frame component of spatiotemporal mapping """
        return (-self.s / self.t)*self.dx(return_array=return_array)

    def comoving_matrix(self):
        """ Operator that constitutes the co-moving frame term """
        return (-self.s / self.t)*self._dx_matrix()

    def change_reference_frame(self, to='comoving'):
        """ Transform to (or from) the co-moving frame depending on the current reference frame

        Parameters
        ----------
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
                shift = -1.0 * self.s
            else:
                return self
        elif to == 'physical':
            if self.frame == 'comoving':
                shift = self.s
            else:
                return self
        else:
            raise ValueError('Trying to change to unrecognizable reference frame.')

        spatial_modes = self.transform(to='spatial_modes').state
        time_vector = np.flipud(np.linspace(0, self.t, num=self.n, endpoint=True)).reshape(-1, 1)
        translation_per_period = shift / self.t
        time_dependent_translations = translation_per_period*time_vector
        thetak = time_dependent_translations.reshape(-1, 1)*spatial_frequencies(self.x, self.m, order=1).ravel()
        cosine_block = np.cos(thetak)
        sine_block = np.sin(thetak)
        real_modes = spatial_modes[:, :-(int(self.m // 2) - 1)]
        imag_modes = spatial_modes[:, -(int(self.m // 2) - 1):]
        frame_rotated_spatial_modes_real = (np.multiply(real_modes, cosine_block)
                                      + np.multiply(imag_modes, sine_block))
        frame_rotated_spatial_modes_imag = (-np.multiply(real_modes, sine_block)
                                      + np.multiply(imag_modes, cosine_block))
        frame_rotated_spatial_modes = np.concatenate((frame_rotated_spatial_modes_real, frame_rotated_spatial_modes_imag), axis=1)

        rotated_orbit = self.__class__(state=frame_rotated_spatial_modes, basis='spatial_modes',
                                       parameters=(self.t, self.x, self.s), frame=to)
        return rotated_orbit.transform(to=self.basis)

    def copy(self):
        return self.__class__(state=self.state.copy(), basis=self.basis, parameters=self.parameters, frame=self.frame)

    def state_vector(self):
        """ Vector which completely describes the orbit."""
        return np.concatenate((self.state.reshape(-1, 1),
                               np.array([[float(self.t)]]),
                               np.array([[float(self.x)]]),
                               np.array([[float(self.s)]])), axis=0)

    def verify_integrity(self):
        """ Check whether the orbit converged to an equilibrium or close-to-zero solution """
        orbit_with_inverted_shift = self.copy()
        orbit_with_inverted_shift.S = -self.s
        residual_imported_S = self.residual()
        residual_negated_S = orbit_with_inverted_shift.residual()
        if residual_imported_S > residual_negated_S:
            orbit_ = orbit_with_inverted_shift
        else:
            orbit_ = self.copy()
        # Take the L_2 norm of the field, if uniformly close to zero, the magnitude will be very small.
        field_orbit = orbit_.transform(to='field')

        # See if the L_2 norm is beneath a threshold value, if so, replace with zeros.
        if field_orbit.norm() < 10**-5 or self.t in [0, 0.]:
            code = 4
            return RelativeEquilibriumOrbitKS(state=np.zeros([self.n, self.m]), basis='field',
                                              parameters=self.parameters).transform(to=self.basis), code
        # Equilibrium is defined by having no temporal variation, i.e. time derivative is a uniformly zero.
        elif self.t in [0., 0]:
            # If there is sufficient evidence that solution is an equilibrium, change its class
            code = 3
            # store T just in case we want to refer to what the period was before conversion to EquilibriumOrbitKS
            return EquilibriumOrbitKS(state=field_orbit.state, basis='field',
                                      parameters=self.parameters).transform(to=self.basis), code
        elif field_orbit.dt().transform(to='field').norm() < 10**-5:
            # If there is sufficient evidence that solution is an equilibrium, change its class
            code = 3
            return RelativeEquilibriumOrbitKS(state=self.transform(to='modes').state, basis='modes',
                                              parameters=self.parameters).transform(to=self.basis), code
        else:
            code = 1
            return orbit_, code

    def from_fundamental_domain(self):
        return self.change_reference_frame(to='comoving')

    def to_fundamental_domain(self):
        return self.change_reference_frame(to='physical')

    def transform(self, to='modes'):
        """ Convert current state to a different basis.
        This instance method is just a wrapper for different
        Fourier transforms. It's purpose is to remove the
        need for the user to keep track of the basis by hand.
        This should be used as opposed to Fourier transforms.
        Parameters
        ----------
        to : str
            One of the following: 'field', 'spatial_modes', 'modes'. Specifies
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
        orbit_in_specified_basis = super().transform(to=to)
        orbit_in_specified_basis.frame = self.frame
        return orbit_in_specified_basis

    def pad(self, size, axis=0):
        """ Checks if in comoving frame then pads. See OrbitKS for more details
        """
        assert self.frame == 'comoving', 'Mode padding requires comoving frame; set padding=False if plotting'
        return super().pad(size, axis=axis)

    def truncate(self, size, axis=0):
        """ Checks if in comoving frame then truncates. See OrbitKS for more details
        """
        assert self.frame == 'comoving', 'Mode truncation requires comoving frame; set padding=False if plotting'
        return super().truncate(size, axis=axis)

    def generate(self, attr='all', **kwargs):
        """ Randomly initialize parameters which are currently zero.

        Parameters
        ----------
        kwargs :
            p_ranges : dict
                keys are parameter_labels, values are uniform sampling intervals or iterables to sample from

        Returns
        -------

        """
        # This will first replace any None valued parameters (or if parameters itself is None)
        super().generate(attr=attr, **kwargs)
        # Can only initialize spatial shift if both the shift and the parameters have been instantiated.
        if attr == 'all' and self.size > 0 and self.s == 0. and self.frame == 'physical':
            shift = calculate_spatial_shift(self.transform(to='spatial_modes').state, self.x, **kwargs)
            parameters_with_shift = tuple(shift if label == 's' else val for label, val in zip(self.parameter_labels(),
                                                                                               self.parameters))
            setattr(self, 'parameters', parameters_with_shift)

    def _jacobian_parameter_derivatives_concat(self, jac_):
        """ Concatenate parameter partial derivatives to Jacobian matrix

        Parameters
        ----------
        jac_ : np.ndArray,
        (N-1) * (M-2) dimensional array resultant from taking the derivative of the spatioatemporal mapping
        with respect to Fourier modes.

        Returns
        -------
        Jacobian augmented with parameter partial derivatives as columns. Required to solve for changes to period,
        space period in optimization process. Makes the system rectangular; needs to be solved by least squares type
        methods.

        """
        # If period is not fixed, need to include dF/dT in jacobian matrix
        if not self.constraints['t']:
            time_period_derivative = (-1.0 / self.t)*(self.dt(return_array=True)
                                                      + (-self.s / self.t)*self.dx(return_array=True)
                                                      ).reshape(-1, 1)
            jac_ = np.concatenate((jac_, time_period_derivative), axis=1)

        # If spatial period is not fixed, need to include dF/dL in jacobian matrix
        if not self.constraints['x']:
            self_field = self.transform(to='field')
            spatial_period_derivative = ((-2.0 / self.x) * self.dx(order=2, return_array=True)
                                         + (-4.0 / self.x) * self.dx(order=4, return_array=True)
                                         + (-1.0 / self.x) * self_field.nonlinear(self_field, return_array=True))
            jac_ = np.concatenate((jac_, spatial_period_derivative.reshape(-1, 1)), axis=1)

        if not self.constraints['s']:
            spatial_shift_derivatives = (-1.0 / self.t)*self.dx(return_array=True)
            jac_ = np.concatenate((jac_, spatial_shift_derivatives.reshape(-1, 1)), axis=1)

        return jac_

    def _jac_lin(self):
        """ Extension of the OrbitKS method that includes the term for spatial translation symmetry"""
        return super()._jac_lin() + self.comoving_matrix()


class AntisymmetricOrbitKS(OrbitKS):

    # def __init__(self, state=None, basis=None, parameters=None, **kwargs):
    #     super().__init__(state=state, basis=basis, parameters=parameters, **kwargs)

    def nonlinear(self, other, return_array=False):
        """ nonlinear computation of the nonlinear term of the Kuramoto-Sivashinsky equation

        """
        # Elementwise product, both self and other should be in physical field basis.
        assert (self.basis == 'field') and (other.basis == 'field')
        # to get around the special behavior of discrete symmetries, will return spatial modes without this workaround.
        nl_orbit = 0.5 * self.statemul(other).dx(computation_basis='spatial_modes', return_basis='modes')
        if return_array:
            return nl_orbit.state
        else:
            return nl_orbit

    def from_fundamental_domain(self, **kwargs):
        """ Overwrite of parent method """
        return self.__class__(state=np.concatenate((self.reflection().state, self.state), axis=1),
                              basis='field', parameters=(self.t, 2*self.x, 0.))

    def pad(self, size, axis=0):
        """ Overwrite of parent method """
        modes = self.transform(to='modes')
        if np.mod(size, 2):
            raise ValueError('New discretization size must be an even number, preferably a power of 2')
        else:
            if axis == 0:
                # Split into real and imaginary components, pad separately.
                padding = (size-modes.N) // 2
                padding_tuple = ((padding, padding), (0, 0))
                padded_modes = np.concatenate((modes.state[:-modes.n, :],
                                               np.pad(modes.state[-modes.n:, :], padding_tuple)), axis=0)
                padded_modes *= np.sqrt(size / modes.N)
            else:
                padding_number = (size-modes.M) // 2
                padded_modes = np.sqrt(size / modes.M) * np.pad(modes.state, ((0, 0), (0, padding_number)))
        return self.__class__(state=padded_modes, basis='modes',
                              parameters=self.parameters).transform(to=self.basis)

    def truncate(self, size, axis=0):
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

    @classmethod
    def _default_parameter_ranges(cls):
        # L=38.5 based on Yueheng Lan and Cvitanovic investigations
        return {'t': (20., 200.), 'x': (38.5, 100.), 's': (0., 0.)}

    @staticmethod
    def default_shape():
        """ The shape of a generic state, see core.py for details
        """
        return 1, 32

    def shapes(self):
        """ State array shapes in different bases.
        """
        return (self.n, self.m), (self.n, self.m - 2), (max([self.n-1, 1]), (int(self.m // 2) - 1))

    def selection_rules(self):
        # Apply the pattern to (int(self.m // 2) - 1) modes
        reflection_selection_rules_integer_flags = np.repeat((np.arange(0, 2*(self.n-1)) % 2).ravel(), (int(self.m // 2) - 1))
        # These indices are used for the transform as well as the transform matrices; therefore they are returned
        # in a format compatible with both; applying .nonzero() yields indices., resize(self.shapes()[2]) yields
        # tensor format.
        return reflection_selection_rules_integer_flags

    def _parse_state(self, state, basis, **kwargs):
        if isinstance(state, np.ndarray):
            self.state = state
        else:
            self.state = np.array([], dtype=float).reshape(0, 0)
            
        if self.size > 0:
            if basis is None:
                raise ValueError('basis must be provided when state is provided')
            elif basis == 'modes':
                n, m = self.shape[0] + 1, 2*self.shape[1] + 2
            elif basis == 'field':
                n, m = self.shape
            elif basis == 'spatial_modes':
                n, m = self.shape[0], self.shape[1]+2
            else:
                raise ValueError('basis parameter equal "field" or "spatial_modes", or "modes"')
            self.discretization = n, m
            self.basis = basis
            # self.n, (int(self.m // 2) - 1) = max([int(self.n // 2) - 1, 1]), int(self.m // 2) - 1
        else:
            self.discretization = None
            self.basis = None

    def _time_transform_matrix(self):
        """

        Notes
        -----
        Dramatic simplification over old code; now just the full DFT matrix plus projection
        """
        return super()._time_transform_matrix()[self.selection_rules().nonzero()[0], :]

    def _inv_time_transform_matrix(self):
        """

        Notes
        -----
        Dramatic simplification over old code; now just transpose of forward dft matrix b.c. orthogonal
        """
        return self._time_transform_matrix().T

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

        _jac_nonlin_left = self._time_transform_matrix().dot(self._dx_matrix(computation_basis='spatial_modes'))
        _jac_nonlin_middle = self._space_transform_matrix().dot(np.diag(self.transform(to='field').state.ravel()))
        _jac_nonlin_right = self._inv_spacetime_transform_matrix()
        _jac_nonlin = _jac_nonlin_left.dot(_jac_nonlin_middle).dot(_jac_nonlin_right)

        return _jac_nonlin

    def _time_transform(self, return_array=False):
        """ Spatial Fourier transform

        Parameters
        ----------

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.
        modes = rfft(self.state, norm='ortho', axis=0)
        spacetime_modes = np.concatenate((modes.real[:-1, -(int(self.m // 2) - 1):], modes.imag[1:-1, -(int(self.m // 2) - 1):]), axis=0)
        spacetime_modes[1:, :] = np.sqrt(2) * spacetime_modes[1:, :]
        if return_array:
            return spacetime_modes
        else:
            return self.__class__(state=spacetime_modes, basis='modes', parameters=self.parameters)

    def _inv_time_transform(self, return_array=False):
        """ Spatial Fourier transform

        Parameters
        ----------

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for unitary normalization.

        modes = self.state
        padding = np.zeros([1, (int(self.m // 2) - 1)])
        time_real = np.concatenate((modes[:-max([int(self.n // 2) - 1,  1]), :], padding), axis=0)
        time_imaginary = np.concatenate((padding, modes[-max([int(self.n // 2) - 1,  1]):, :], padding), axis=0)
        complex_modes = time_real + 1j*time_imaginary
        complex_modes[1:, :] /= np.sqrt(2)
        imaginary_space_modes = irfft(complex_modes, norm='ortho', axis=0)
        space_modes = np.concatenate((np.zeros(imaginary_space_modes.shape), imaginary_space_modes), axis=1)
        if return_array:
            return space_modes
        else:
            return self.__class__(state=space_modes, basis='spatial_modes', parameters=self.parameters)

    def to_fundamental_domain(self, half=0, **kwargs):
        """ Overwrite of parent method """
        if half == 0:
            f_domain = self.transform(to='field').state[:, :-int(self.m//2)]
        else:
            f_domain = self.transform(to='field').state[:, -int(self.m//2):]

        return self.__class__(state=f_domain, basis='field', parameters=(self.t, self.x / 2.0, 0.))


class ShiftReflectionOrbitKS(OrbitKS):

    # def __init__(self, state=None, basis=None, parameters=None, **kwargs):
    #     """ Orbit subclass for solutions with spatiotemporal shift-reflect symmetry
    #
    #
    #
    #     Parameters
    #     ----------
    #     state
    #     basis
    #     T
    #     L
    #     kwargs
    #
    #     Notes
    #     -----
    #     Technically could inherit some functions from AntisymmetricOrbitKS but in regards to the Physics
    #     going on it is more coherent to have it as a subclass of OrbitKS only.
    #     """
    #     super().__init__(state=state, basis=basis, parameters=parameters, **kwargs)

    def nonlinear(self, other, return_array=False):
        """ nonlinear computation of the nonlinear term of the Kuramoto-Sivashinsky equation

        """
        # Elementwise product, both self and other should be in physical field basis.
        assert (self.basis == 'field') and (other.basis == 'field')
        # to get around the special behavior of discrete symmetries, will return spatial modes without this workaround.
        nl_orbit = 0.5 * self.statemul(other).dx(computation_basis='spatial_modes', return_basis='modes')
        if return_array:
            return nl_orbit.state
        else:
            return nl_orbit

    def pad(self, size, axis=0):
        """ Overwrite of parent method """
        modes = self.transform(to='modes')
        if np.mod(size, 2):
            raise ValueError('New discretization size must be an even number, preferably a power of 2')
        else:
            if axis == 0:
                padding = (size-modes.N) // 2
                padding_tuple = ((padding, padding), (0, 0))
                padded_modes = np.concatenate((modes.state[:-modes.n, :],
                                               np.pad(modes.state[-modes.n:, :], padding_tuple)), axis=0)
                padded_modes *= np.sqrt(size / modes.N)
            else:
                padding_number = (size-modes.M) // 2
                padded_modes = np.sqrt(size / modes.M) * np.pad(modes.state, ((0, 0), (0, padding_number)))

        return self.__class__(state=padded_modes, basis='modes',
                              parameters=self.parameters).transform(to=self.basis)

    def truncate(self, size, axis=0):
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

    def selection_rules(self):
        # equivalent to indices 0 + j from thesis; time indices go like {0, j, j}
        # i = np.arange(0, self.n//2)[:, None]
        i = np.repeat(np.arange(1, self.n//2) % 2, 2)
        # Use of np.block is essentially equivalent to two concatenate calls. This gets the correct pattern.
        selection_tensor_pattern = np.concatenate(([0], i, [0], i[1:], [0]))
        # selection_tensor_pattern = np.block([[i % 2, (i+1) % 2], [i[1:] % 2, (i[1:]+1) % 2]])
        # Apply the pattern to (int(self.m // 2) - 1) modes
        shiftreflection_selection_rules_integer_flags = np.repeat(selection_tensor_pattern.ravel(), (int(self.m // 2) - 1))
        # These indices are used for the transform as well as the transform matrices; therefore they are returned
        # in a format compatible with both; applying .nonzero() yields indices., resize(self.shapes()[2]) yields
        # tensor format.
        return shiftreflection_selection_rules_integer_flags

    def shapes(self):
        """ State array shapes in different bases. See core.py for details.
        """
        return (self.n, self.m), (self.n, self.m - 2), (max([self.n-1, 1]), (int(self.m // 2) - 1))

    def to_fundamental_domain(self, half=0):
        """ Overwrite of parent method """
        field = self.transform(to='field').state
        if half == 0:
            f_domain = field[-int(self.n // 2):, :]
        else:
            f_domain = field[:-int(self.n // 2), :]
        return self.__class__(state=f_domain, basis='field', parameters=(self.t / 2.0, self.x, 0.))

    def from_fundamental_domain(self):
        """ Reconstruct full field from discrete fundamental domain """
        field = np.concatenate((self.reflection().state, self.state), axis=0)
        return self.__class__(state=field, basis='field', parameters=(2*self.t, self.x, 0.))

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

        _jac_nonlin_left = self._time_transform_matrix().dot(self._dx_matrix(computation_basis='spatial_modes'))
        _jac_nonlin_middle = self._space_transform_matrix().dot(np.diag(self.transform(to='field').state.ravel()))
        _jac_nonlin_right = self._inv_spacetime_transform_matrix()
        _jac_nonlin = _jac_nonlin_left.dot(_jac_nonlin_middle).dot(_jac_nonlin_right)

        return _jac_nonlin

    def _parse_state(self, state, basis, **kwargs):
        if isinstance(state, np.ndarray):
            self.state = state
        else:
            self.state = np.array([], dtype=float).reshape(0, 0)
        if self.size > 0:
            if basis is None:
                raise ValueError('basis must be provided when state is provided')
            elif basis == 'modes':
                n, m = self.shape[0] + 1, 2*self.shape[1] + 2
            elif basis == 'field':
                n, m = self.shape
            elif basis == 'spatial_modes':
                n, m = self.shape[0], self.shape[1]+2
            else:
                raise ValueError('basis parameter equal "field" or "spatial_modes", or "modes"')
            self.discretization = n, m
            self.basis = basis
            # self.n, (int(self.m // 2) - 1) = max([int(self.n // 2) - 1,  1]), int(self.m // 2) - 1
        else:
            self.discretization = None
            self.basis = None

    def _time_transform(self, return_array=False):
        """ Spatial Fourier transform

        Parameters
        ----------

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        # Take rfft, accounting for orthogonal normalization.
        assert self.basis == 'spatial_modes'
        modes = rfft(self.state, norm='ortho', axis=0)
        # Project onto shift-reflection subspace.
        modes[::2, :-(int(self.m // 2) - 1)] = 0
        modes[1::2, -(int(self.m // 2) - 1):] = 0
        # Due to projection, can add the different components without mixing information, this allows
        # us to avoid a complex operation like shuffling.
        spacetime_modes = np.concatenate((modes.real[:-1, :-(int(self.m // 2) - 1)] + modes.real[:-1, -(int(self.m // 2) - 1):],
                                          modes.imag[1:-1, :-(int(self.m // 2) - 1)] + modes.imag[1:-1, -(int(self.m // 2) - 1):]), axis=0)
        spacetime_modes[1:, :] = np.sqrt(2)*spacetime_modes[1:, :]
        if return_array:
            return spacetime_modes
        else:
            return self.__class__(state=spacetime_modes, basis='modes', parameters=self.parameters)

    def _inv_time_transform(self, return_array=False):
        """ Spatial Fourier transform

        Parameters
        ----------
        return_array : bool
            Whether to return np.ndarray or Orbit subclass instance

        Returns
        -------
        OrbitKS :
            OrbitKS whose state is in the spatial Fourier mode basis.

        """
        assert self.basis == 'modes'
        modes = self.transform(to='modes').state
        padding = np.zeros([1, (int(self.m // 2) - 1)])
        time_real = np.concatenate((modes[:-max([int(self.n // 2) - 1,  1]), :], padding), axis=0)
        time_imaginary = np.concatenate((padding, modes[-max([int(self.n // 2) - 1,  1]):, :], padding), axis=0)
        complex_modes = time_real + 1j*time_imaginary
        complex_modes = np.concatenate((complex_modes, complex_modes), axis=1)
        complex_modes[1:, :] /= np.sqrt(2)
        complex_modes[::2, :-(int(self.m // 2) - 1)] = 0
        complex_modes[1::2, -(int(self.m // 2) - 1):] = 0
        spatial_modes = irfft(complex_modes, norm='ortho', axis=0)
        if return_array:
            return spatial_modes
        else:
            return self.__class__(state=spatial_modes, basis='spatial_modes', parameters=self.parameters)

    def _time_transform_matrix(self):
        """

        Notes
        -----
        Dramatic simplification over old code; now just the full DFT matrix plus projection
        """
        return super()._time_transform_matrix()[self.selection_rules().nonzero()[0], :]

    def _inv_time_transform_matrix(self):
        """

        Notes
        -----
        Dramatic simplification over old code; now just transpose of forward dft matrix b.c. orthogonal
        """
        return self._time_transform_matrix().transpose()


class EquilibriumOrbitKS(AntisymmetricOrbitKS):

    # def __init__(self, state=None, basis=None, parameters=None, **kwargs):
    #     """ Subclass for equilibrium solutions (all of which are antisymmetric w.r.t. space).
    #     Parameters
    #     ----------
    #     state
    #     basis
    #     T
    #     L
    #     S
    #     kwargs
    #
    #     Notes
    #     -----
    #     For convenience, this subclass accepts any (even) value for the time discretization. Only a single time point
    #     is required however to fully represent the solution and therefore perform any computations. If the
    #     discretization size is greater than 1 then then different bases will have the following shapes: field (N, M).
    #     spatial modes = (N, m), spatiotemporal modes (1, m). In other words, discretizations
    #     of this type can still be used in the optimization codes but will be much more inefficient.
    #     The reason for this choice is because it is possible
    #     to start with a spatiotemporal orbit with no symmetry (i.e. OrbitKS) and still end up at an equilibrium
    #     solution. Therefore, I am accommodating transformations from other orbit types to EquilibriumOrbitKS. To
    #     make the computations more efficient all that is required is usage of the method
    #     self.optimize_for_calculations(), which converts N -> 1, making the shape of the state (1, M) in the
    #     physical field basis. Also can inherit more methods with this choice.
    #     More details are included in the thesis and in the documentation.
    #     While only the imaginary components of the spatial modes are non-zero, both real and imaginary components are
    #     kept to allow for odd order spatial derivatives, required for the nonlinear term. Other allowed operations such
    #     as rotation are preferably performed after converting to a different symmetry type such as AntisymmetricOrbitKS
    #     or OrbitKS.
    #
    #     """
    #     super().__init__(state=state, basis=basis, parameters=parameters, **kwargs)

    def dae(self, **kwargs):
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
        mapping_modes = (self.dx(order=2, return_array=True)
                         + self.dx(order=4, return_array=True)
                         + orbit_field.nonlinear(orbit_field, return_array=True))
        return self.__class__(state=mapping_modes, basis='modes', parameters=self.parameters)

    def rmatvec(self, other, **kwargs):
        """ Overwrite of parent method """
        assert (self.basis == 'modes') and (other.basis == 'modes')
        self_field = self.transform(to='field')
        rmatvec_modes = (other.dx(order=2, return_array=True)
                         + other.dx(order=4, return_array=True)
                         + self_field.rnonlinear(other, return_array=True))

        other_modes_in_vector_form = other.state.ravel()
        if not self.constraints['x']:
            # change in L, dL, equal to DF/DL * v
            rmatvec_L = ((-2.0 / self.x) * self.dx(order=2, return_array=True)
                         + (-4.0 / self.x) * self.dx(order=4, return_array=True)
                         + (-1.0 / self.x) * self_field.nonlinear(self_field, return_array=True)
                         ).ravel().dot(other_modes_in_vector_form)
        else:
            rmatvec_L = 0

        return self.__class__(state=rmatvec_modes, basis='modes', parameters=(0., rmatvec_L, 0.))

    def rmatvec_parameters(self, self_field, other):
        other_modes_in_vector_form = other.state.ravel()
        if not self.constraints['x']:
            # change in L, dL, equal to DF/DL * v
            rmatvec_L = ((-2.0 / self.x) * self.dx(order=2, return_array=True)
                         + (-4.0 / self.x) * self.dx(order=4, return_array=True)
                         + (-1.0 / self.x) * self_field.nonlinear(self_field, return_array=True)
                         ).ravel().dot(other_modes_in_vector_form)
        else:
            rmatvec_L = 0

        return 0., rmatvec_L, 0.

    def state_vector(self):
        """ Overwrite of parent method """
        return np.concatenate((self.state.reshape(-1, 1),
                               np.array([[float(self.x)]])), axis=0)

    def from_fundamental_domain(self, **kwargs):
        """ Overwrite of parent method """
        return self.__class__(state=np.concatenate((self.reflection().state, self.state), axis=1),
                              basis='field', parameters=(0., 2.0*self.x, 0.))

    def to_fundamental_domain(self, half=0, **kwargs):
        """ Overwrite of parent method """
        if half == 0:
            f_domain = self.transform(to='field').state[:, :-int(self.m//2)]
        else:
            f_domain = self.transform(to='field').state[:, -int(self.m//2):]
        return self.__class__(state=f_domain, basis='field', parameters=(0., self.x / 2.0, 0.))

    def pad(self, size, axis=0):
        """ Overwrite of parent method

        Notes
        -----
        If starting and ending in the spatiotemporal modes basis, this will only create an instance with a different
        value of time dimensionality attribute 'N'.
        """
        spatial_modes = self.transform(to='spatial_modes')
        if axis == 0:
            # Not technically zero-padding, just copying. Just can't be in temporal mode basis
            # because it is designed to only represent the zeroth modes.
            padded_spatial_modes = np.tile(spatial_modes.state[0, :].reshape(1, -1), (size, 1))
            return self.__class__(state=padded_spatial_modes, basis='spatial_modes',
                                  parameters=self.parameters, N=size).transform(to=self.basis)
        else:
            # Split into real and imaginary components, pad separately.
            complex_modes = spatial_modes.state[:, -spatial_modes.m:]
            real_modes = np.zeros(complex_modes.shape)
            padding_number = (size-spatial_modes.M) // 2
            padding = np.zeros([spatial_modes.state.shape[0], padding_number])
            padded_modes = np.sqrt(size / spatial_modes.M) * np.concatenate((real_modes, padding,
                                                                       complex_modes, padding), axis=1)
            return self.__class__(state=padded_modes, basis='spatial_modes',
                                  parameters=self.parameters).transform(to=self.basis)

    def truncate(self, size, axis=0):
        """ Overwrite of parent method """
        if axis == 0:
            spatial_modes = self.transform(to='spatial_modes')
            truncated_spatial_modes = spatial_modes.state[-size:, :]
            return self.__class__(state=truncated_spatial_modes, basis='spatial_modes',
                                  parameters=self.parameters).transform(to=self.basis)
        else:
            modes = self.transform(to='modes')
            truncate_number = int(size // 2) - 1
            truncated_modes = modes.state[:, :truncate_number]
            return self.__class__(state=truncated_modes,  basis='modes',
                                  parameters=self.parameters, N=self.n).transform(to=self.basis)

    @classmethod
    def _default_parameter_ranges(cls):
        # minimum L=2*pi based on fundamental orbit.
        return {'t': (20., 200.), 'x': (2*pi, 100.), 's': (0., 0.)}

    @classmethod
    def parameter_based_discretization(cls, dimensions, **kwargs):
        """ Follow orbithunter conventions for discretization size.


        Parameters
        ----------
        parameters : tuple
            tuple containing (T, L, S) i.e. OrbitKS().parameters

        kwargs :
            resolution : str
                Takes values 'coarse', 'normal', 'fine'. These options return one of three orbithunter conventions for
                the discretization size.
            N : int, default None
                Temporal discretization size, if provided
            M : int, default None
                Spatial discretization size, if provided
        Returns
        -------
        int, int
        The new spatiotemporal field discretization; number of time points (rows) and number of space points (columns)

        Notes
        -----
        This function should only ever be called by rediscretize, the returned values can always be accessed by
        the appropriate attributes of the rediscretized orbit_.
        """
        # Change the default to N = 1 from N = None, this ensures that the temporal period (t=0) is never used
        # unless for some reason N=None is passed.
        kwargs.setdefault('N', 1)
        N, M = super().parameter_based_discretization(dimensions, **kwargs)
        return N, M

    def shapes(self):
        """ State array shapes in different bases. See core.py for details.
        """
        return (self.n, self.m), (self.n, self.m - 2), (1, (int(self.m // 2) - 1))

    def precondition(self, **kwargs):
        """ Precondition a vector with the inverse (aboslute value) of linear spatial terms

        Parameters
        ----------
        parameters : tuple
            Pair of tuples of parameters required for differentiation


        Returns
        -------
        target : OrbitKS
            Return the OrbitKS instance, modified by preconditioning.

        Notes
        -----
        Often we want to precondition a state derived from a mapping or rmatvec (gradient descent step),
        with respect to ANOTHER orbit's (current state's) parameters.
        """
        pmult = kwargs.get('pmult', self.preconditioning_parameters())
        p_multipliers = 1.0 / (np.abs(elementwise_dxn(*pmult[1], order=2))
                               + elementwise_dxn(*pmult[1], order=4))

        preconditioned_state = np.multiply(self.state, p_multipliers)
        param_powers = kwargs.get('pexp', (0, 4))
        # Precondition the change in T and L so that they do not dominate
        if not self.constraints['x']:
            # self is the orbit being preconditioned, i.e. the correction orbit; by default this is dL = dL / L^4
            L = self.x * (pmult[1][0]**-param_powers[1])
        else:
            L = self.x

        return self.__class__(state=preconditioned_state, parameters=(0., L, 0.), basis='modes')

    def verify_integrity(self):
        """ Check whether the orbit converged to an equilibrium or close-to-zero solution """
        # Take the L_2 norm of the field, if uniformly close to zero, the magnitude will be very small.
        field_orbit = self.transform(to='field')

        # See if the L_2 norm is beneath a threshold value, if so, replace with zeros.
        if field_orbit.norm() < 10**-5:
            code = 4
            return self.__class__(state=np.zeros([self.n, self.m]), basis='field',
                                  parameters=self.parameters).transform(to=self.basis), code
        else:
            return self, 1

    def _parse_state(self, state, basis, **kwargs):
        if isinstance(state, np.ndarray):
            self.state = state
        else:
            self.state = np.array([], dtype=float).reshape(0, 0)

        if self.size > 0:
            if len(self.shape) == 1:
                self.state = state.reshape(1, -1)
            if basis is None:
                raise ValueError('basis must be provided when state is provided')
            elif basis == 'modes':
                self.state = self.state[0, :].reshape(1, -1)
                n = kwargs.get('N', None) or 1
                m = 2 * self.shape[1] + 2
            elif basis == 'field':
                n, m = self.shape
            elif basis == 'spatial_modes':
                n, m = self.shape[0], self.shape[1] + 2
            else:
                raise ValueError('basis parameter equal "field" or "spatial_modes", or "modes"')
            self.discretization = n, m
            self.basis = basis
        else:
            self.discretization = None
            self.basis = None

    # def _parse_parameters(self, parameters, **kwargs):
    #     # New addition, keep track of constraints via attribute instead of passing them around everywhere.
    #     self.constraints = kwargs.get('constraints', {'t': False, 'x': False, 's': False})
    #
    #     # The default value of nonzero_parameters is False. If its true, assign random value to L
    #     if parameters[1] == 0. and kwargs.get('nonzero_parameters', False):
    #         if kwargs.get('seed', None) is not None:
    #             np.random.seed(kwargs.get('seed', None)+1)
    #         self.x = (kwargs.get('L_min', 22.)
    #                   + (kwargs.get('L_max', 66.) - kwargs.get('L_min', 22.))*np.random.rand())
    #     else:
    #         self.x = float(parameters[1])
    #     # for the sake of uniformity of save format, technically 0 will be returned even if not defined because
    #     # of __getattr__ definition.
    #     self.t = 0.
    #     self.s = 0.

    def _jac_lin(self):
        """ Extension of the OrbitKS method that includes the term for spatial translation symmetry"""
        return self._dx_matrix(order=2) + self._dx_matrix(order=4)

    def _jacobian_parameter_derivatives_concat(self, jac_, ):
        """ Concatenate parameter partial derivatives to Jacobian matrix

        Parameters
        ----------
        jac_ : np.ndArray,
        (N-1) * (M-2) dimensional array resultant from taking the derivative of the spatioatemporal mapping
        with respect to Fourier modes.

        Returns
        -------
        Jacobian augmented with parameter partial derivatives as columns. Required to solve for changes to period,
        space period in optimization process. Makes the system rectangular; needs to be solved by least squares type
        methods.

        """
        # If spatial period is not fixed, need to include dF/dL in jacobian matrix
        if not self.constraints['x']:
            self_field = self.transform(to='field')
            spatial_period_derivative = ((-2.0 / self.x) * self.dx(order=2, return_array=True)
                                         + (-4.0 / self.x) * self.dx(order=4, return_array=True)
                                         + (-1.0 / self.x) * self_field.nonlinear(self_field, return_array=True))
            jac_ = np.concatenate((jac_, spatial_period_derivative.reshape(-1, 1)), axis=1)

        return jac_

    def _inv_time_transform_matrix(self):
        """ Overwrite of parent method

        Notes
        -----
        Originally this transform just selected the antisymmetric spatial modes (imaginary component),
        but in order to be consistent with all other time transforms, I will actually apply the normalization
        constant associated with a forward in time transformation. The reason for this is for comparison
        of states between different subclasses.
        """
        return np.tile(np.concatenate((0*np.eye((int(self.m // 2) - 1)), np.eye((int(self.m // 2) - 1))), axis=0), (self.n, 1))

    def _time_transform_matrix(self):
        """ Overwrite of parent method """

        time_dft_mat = np.tile(np.concatenate((0*np.eye((int(self.m // 2) - 1)), np.eye((int(self.m // 2) - 1))), axis=1), (1, self.n))
        time_dft_mat[:, 2*(int(self.m // 2) - 1):] = 0
        return time_dft_mat

    def _time_transform(self, return_array=False):
        """ Overwrite of parent method

        Notes
        -----
        Taking the RFFT, with orthogonal normalization, of a constant time series defined on N points is equivalent
        to multiplying the constant value by sqrt(N). This is because the transform sums over N repeats of the same
        value and then divides by 1/sqrt(N). i.e. (N * C)/sqrt(N) = sqrt(N) * C. Therefore we can save some time by
        just doing this without calling the rfft function.
        """
        # Select the nonzero (imaginary) components of modes and transform in time (w.r.t. axis=0).
        spacetime_modes = self.state[0, -(int(self.m // 2) - 1):].reshape(1, -1)
        if return_array:
            return spacetime_modes
        else:
            return self.__class__(state=spacetime_modes, basis='modes',
                                  parameters=self.parameters, N=self.n)

    def _inv_time_transform(self, return_array=False):
        """ Overwrite of parent method

        Notes
        -----
        Taking the IRFFT, with orthogonal normalization is equivalent to dividing by the normalization constant; because
        there would only be
        """
        real = np.zeros(self.state.shape)
        imaginary = self.state
        spatial_modes = np.tile(np.concatenate((real, imaginary), axis=1), (self.n, 1))
        if return_array:
            return spatial_modes
        else:
            return self.__class__(state=spatial_modes, basis='spatial_modes',
                                  parameters=self.parameters, N=self.n)


class RelativeEquilibriumOrbitKS(RelativeOrbitKS):

    # def __init__(self, state=None, basis=None, parameters=None, frame='comoving', **kwargs):
    #     super().__init__(state=state, basis=basis, parameters=parameters, frame=frame, **kwargs)

    def dt(self, order=1, return_array=False):
        """ A time derivative of the current state.

        Parameters
        ----------
        order :int
            The order of the derivative.

        return_array : bool
            Whether to return np.ndarray or Orbit

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

    def dae(self, **kwargs):
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
        mapping_modes = (modes.dx(order=2, return_array=True)
                         + modes.dx(order=4, return_array=True)
                         + field.nonlinear(field, return_array=True)
                         + modes.comoving_mapping_component(return_array=True))
        return self.__class__(state=mapping_modes, basis='modes', parameters=self.parameters)

    @classmethod
    def parameter_based_discretization(cls, dimensions, **kwargs):
        """ Subclassed method for equilibria.
        """
        kwargs.setdefault('N', 1)
        N, M = super().parameter_based_discretization(dimensions, **kwargs)
        return N, M

    def shapes(self):
        """ State array shapes in different bases. See core.py for details.
        """
        return (self.n, self.m), (self.n, self.m - 2), (1, self.m-2)

    def verify_integrity(self):
        """ Check whether the orbit converged to an equilibrium or close-to-zero solution """
        # Take the L_2 norm of the field, if uniformly close to zero, the magnitude will be very small.
        orbit_with_inverted_shift = self.copy()
        orbit_with_inverted_shift.S = -self.s
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
            return RelativeEquilibriumOrbitKS(state=np.zeros(self.discretization), basis='field',
                                              parameters=self.parameters).transform(to=self.basis), code
        else:
            code = 1
            return orbit_, code

    def to_fundamental_domain(self):
        return self.change_reference_frame(to='physical')

    def from_fundamental_domain(self):
        """ For compatibility purposes with plotting and other utilities """
        return self.change_reference_frame(to='physical')

    def pad(self, size, axis=0):
        """ Overwrite of parent method

        Notes
        -----
        If starting and ending in the spatiotemporal modes basis, this will only create an instance with a different
        value of time dimensionality attribute 'N'.
        """
        assert self.frame == 'comoving', 'Transform to comoving frame before padding modes'


        if np.mod(size, 2):
            raise ValueError('New discretization size must be an even number, preferably a power of 2')
        else:
            if axis == 0:
                # Not technically zero-padding, just copying. Just can't be in temporal mode basis
                # because it is designed to only represent the zeroth modes.
                spatial_modes = self.transform(to='spatial_modes')
                paddeds_spatial_modes = np.tile(spatial_modes.state[-1, :].reshape(1, -1), (size, 1))
                return self.__class__(state=paddeds_spatial_modes, basis='spatial_modes',
                                      parameters=self.parameters).transform(to=self.basis)
            else:
                modes = self.transform(to='modes')
                padding = (size-modes.M) // 2
                padding_tuple = ((0, 0), (padding, padding))
                padded_modes = np.concatenate((modes.state[:, :-modes.m],
                                               np.pad(modes.state[:, -modes.m:], padding_tuple)), axis=1)
                padded_modes *= np.sqrt(size / modes.M)
                return self.__class__(state=padded_modes, basis='modes',
                                      parameters=self.parameters).transform(to=self.basis)

    def truncate(self, size, axis=0):
        """ Subclassed method to handle RelativeEquilibriumOrbitKS mode's shape.
        """
        assert self.frame == 'comoving', 'Transform to comoving frame before truncating modes'
        if axis == 0:
            truncated_spatial_modes = self.transform(to='spatial_modes').state[-size:, :]
            self.__class__(state=truncated_spatial_modes, basis='spatial_modes', parameters=self.parameters
                           ).transform(to=self.basis)
        else:
            truncate_number = int(size // 2) - 1
            # Split into real and imaginary components, truncate separately.
            spatial_modes = self.transform(to='spatial_modes')
            first_half = spatial_modes.state[:, :truncate_number]
            second_half = spatial_modes.state[:, -spatial_modes.m:-spatial_modes.m + truncate_number]
            truncated_spatial_modes = np.sqrt(size / spatial_modes.M) * np.concatenate((first_half, second_half), axis=1)
        return self.__class__(state=truncated_spatial_modes, basis=self.basis,
                              parameters=self.parameters).transform(to=self.basis)

    def _parse_state(self, state, basis, **kwargs):
        # This is the best way I've found for passing modes but also wanting N != 1. without specifying
        # the keyword argument.
        if isinstance(state, np.ndarray):
            self.state = state
        else:
            self.state = np.array([], dtype=float).reshape(0, 0)

        if self.size > 0:
            if len(self.shape) == 1:
                self.state = self.state.reshape(1, -1)
            if basis is None:
                raise ValueError('basis must be provided when state is provided')
            elif basis == 'modes':
                self.state = self.state[0, :].reshape(1, -1)
                n = kwargs.get('N', None) or 1
                m = self.shape[1] + 2
            elif basis == 'field':
                n, m = self.shape
            elif basis == 'spatial_modes':
                n, m = self.shape[0], self.shape[1] + 2
            else:
                raise ValueError('basis parameter equal "field" or "spatial_modes", or "modes"')
            # To allow for multiple time point fields and spatial modes, for plotting purposes.
            self.discretization = n, m
            self.basis = basis
        else:
            self.discretization = None
            self.basis = None

    def _inv_time_transform_matrix(self):
        """ Overwrite of parent method

        Notes
        -----
        Originally this transform just selected the antisymmetric spatial modes (imaginary component),
        but in order to be consistent with all other time transforms, I will actually apply the normalization
        constant associated with a forward in time transformation. The reason for this is for comparison
        of states between different subclasses.
        """
        return np.tile(np.eye(self.m-2), (self.n, 1))

    def _time_transform_matrix(self):
        """ Overwrite of parent method

        Notes
        -----
        Input state is [N, M-2] dimensional array which is to be sliced to return only the last row.
        N * (M-2) repeats of modes coming in, M-2 coming out, so M-2 rows.

        """

        dft_mat = np.tile(np.eye(self.m-2), (1, self.n))
        dft_mat[:, self.m-2:] = 0
        return dft_mat

    def _time_transform(self, return_array=False):
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
        if return_array:
            return spacetime_modes
        else:
            return self.__class__(state=spacetime_modes, basis='modes',
                                  parameters=self.parameters, N=self.n)

    def _inv_time_transform(self, return_array=False):
        """ Overwrite of parent method

        Notes
        -----
        Taking the IRFFT, with orthogonal normalization is equivalent to dividing by the normalization constant; because
        there would only be
        """
        spatial_modes = np.tile(self.state[0, :].reshape(1, -1), (self.n, 1))
        if return_array:
            return spatial_modes
        else:
            return self.__class__(state=spatial_modes, basis='spatial_modes', parameters=self.parameters)

    def _jac_lin(self):
        """ Extension of the OrbitKS method that includes the term for spatial translation symmetry"""
        return self._dx_matrix(order=2) + self._dx_matrix(order=4) + self.comoving_matrix()

    def _jacobian_parameter_derivatives_concat(self, jac_):
        """ Concatenate parameter partial derivatives to Jacobian matrix

        Parameters
        ----------
        jac_ : np.ndArray,
            (N-1) * (M-2) dimensional array resultant from taking the derivative of the spatioatemporal mapping
            with respect to Fourier modes.

        Returns
        -------
        Jacobian augmented with parameter partial derivatives as columns. Required to solve for changes to period,
        space period in optimization process. Makes the system rectangular; needs to be solved by least squares type
        methods.

        """
        # If period is not fixed, need to include dF/dT in jacobian matrix
        if not self.constraints['t']:
            time_period_derivative = (-1.0 / self.t)*self.comoving_mapping_component(return_array=True).reshape(-1, 1)
            jac_ = np.concatenate((jac_, time_period_derivative), axis=1)

        # If spatial period is not fixed, need to include dF/dL in jacobian matrix
        if not self.constraints['x']:
            self_field = self.transform(to='field')
            spatial_period_derivative = ((-2.0 / self.x) * self.dx(order=2, return_array=True)
                                         + (-4.0 / self.x) * self.dx(order=4, return_array=True)
                                         + (-1.0 / self.x) * self_field.nonlinear(self_field, return_array=True))
            jac_ = np.concatenate((jac_, spatial_period_derivative.reshape(-1, 1)), axis=1)

        if not self.constraints['s']:
            spatial_shift_derivatives = (-1.0 / self.t)*self.dx(return_array=True)
            jac_ = np.concatenate((jac_, spatial_shift_derivatives.reshape(-1, 1)), axis=1)

        return jac_
