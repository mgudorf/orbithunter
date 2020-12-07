from json import dumps
import os
import h5py
import numpy as np

__all__ = ['Orbit', 'convert_class']

"""
The core class for all orbithunter calculations. The methods listed are the ones used in the other modules. If
full functionality isn't currently desired then I recommend only implementing the methods used in optimize.py,
saving data to disk, and plotting. Of course this is in addition to the dunder methods such as __init__. 

While not listed here explicitly, this package is fundamentally a spectral method based package. So in order
to write the functions rmatvec, matvec, spatiotemporal mapping, one will necessarily have to include
methods for differentiation, basis transformations, etc. I do not include them because different equations
have different dimensions and hence will have different transforms. All transforms should be wrapped by
the method .transform(). The spatiotemporal basis should be labeled as 'modes', the physical field should be
labeled as 'field'. There are no assumptions on what "field" and "modes" actually mean, so the physical state space
need not be an actual field. 

In order for all numerical methods to work, the mandatory methods compute the matrix-vector products rmatvec = J^T * x,
matvec = J * x, and must be able to construct the Jacobian = J. ***NOTE: the matrix vector products SHOULD NOT
explicitly construct the Jacobian matrix.***

"""


class Orbit:
    """ Base class for all equations


    Notes
    -----
    Methods listed here are required to have everything work.
    """

    def __init__(self, state=None, basis='field', parameters=(0.,), **kwargs):

        if state is not None:
            self._parse_parameters(parameters, **kwargs)
            self._parse_state(state, basis, **kwargs)
        else:
            # If the state is not passed, then it will be randomly generated. This will require referencing the
            # dimensions, expected to be nonzero to define the collocation grid. Therefore, it is required to
            # either provide
            self._parse_parameters(parameters, nonzero_parameters=kwargs.pop('nonzero_parameters', True), **kwargs)
            # Pass the newly generated parameter values, there are the originals if they were not 0's.
            self._random_initial_condition(self.parameters, **kwargs).transform(to=basis)

    def __add__(self, other):
        """ Addition of Orbit states

        Parameters
        ----------
        other : Orbit
        Should have same class as self. Should be in same basis as self.
        Notes
        -----
        Adding two spatiotemporal velocity fields u(t, x) + v(t, x)
        """
        return self.__class__(state=(self.state + other.state), basis=self.basis,
                              parameters=self.parameters)

    def __radd__(self, other):
        """ Addition of Orbit states

        Parameters
        ----------
        other : Orbit
        Should have same class as self. Should be in same basis as self.
        Notes
        -----
        Adding two spatiotemporal velocity fields u(t, x) + v(t, x)

        Notes
        -----
        This is the same as __add__ by Python makes the distinction between where the operator is, i.e. x + vs. + x.
        """
        return self.__class__(state=(self.state + other.state), basis=self.basis,
                              parameters=self.parameters)

    def __sub__(self, other):
        """ Subtraction of orbit states

        Parameters
        ----------
        other : Orbit
        Should have same class as self. Should be in same basis as self.
        Notes
        -----
        Subtraction of two spatiotemporal states self - other
        """
        return self.__class__(state=(self.state-other.state), basis=self.basis,
                              parameters=self.parameters)

    def __rsub__(self, other):
        """ Subtraction of orbit states

        Parameters
        ----------
        other : Orbit
        Should have same class as self. Should be in same basis as self.
        Notes
        -----
        Subtraction of two spatiotemporal states other - self
        """
        return self.__class__(state=(other.state - self.state), basis=self.basis,
                              parameters=self.parameters)

    def __mul__(self, num):
        """ Scalar multiplication of state values

        Parameters
        ----------
        num : float
            Scalar value to multiply by.

        """
        return self.__class__(state=np.multiply(num, self.state), basis=self.basis,
                              parameters=self.parameters)

    def __rmul__(self, num):
        """ Scalar multiplication of state values

        Parameters
        ----------
        num : float
            Scalar value to multiply by.

        """
        return self.__class__(state=np.multiply(num, self.state), basis=self.basis,
                              parameters=self.parameters)

    def __truediv__(self, num):
        """ Scalar division of state values

        Parameters
        ----------
        num : float
            Scalar value to divide by
        """
        return self.__class__(state=np.divide(self.state, num), basis=self.basis,
                              parameters=self.parameters)

    def __floordiv__(self, num):
        """ Scalar multiplication

        Parameters
        ----------
        num : float
            Scalar value to division by.

        Notes
        -----
        Returns largest integer smaller or equal to the division of the inputs, of the state. This isn't useful
        but I'm including it because it's a fairly common binary operation and might be useful in some circumstances.

        """
        return self.__class__(state=np.floor_divide(self.state, num), basis=self.basis,
                              parameters=self.parameters)

    def __pow__(self, power):
        """ Exponentiate a state

        Parameters
        ----------
        power : float
            Exponent
        """
        return self.__class__(state=self.state**power, basis=self.basis,
                              parameters=self.parameters)

    def __str__(self):
        """ String name
        Returns
        -------
        str :
            Of the form 'Orbit'
        """
        return self.__class__.__name__

    def __repr__(self):
        # alias to save space
        dict_ = {'basis': self.basis,
                 'parameters': tuple(str(np.round(p, 4)) for p in self.parameters),
                 'field_shape': tuple(str(d) for d in self.field_shape)}
        # convert the dictionary to a string via json.dumps
        dictstr = dumps(dict_)
        return self.__class__.__name__ + '(' + dictstr + ')'

    def cost_function_gradient(self, dae, **kwargs):
        preconditioning = kwargs.get('preconditioning', False)
        if preconditioning:
            gradient = (self.rmatvec(dae, **kwargs)
                        ).precondition(self.preconditioning_parameters, **kwargs)
        else:
            gradient = self.rmatvec(dae, **kwargs)
        return gradient

    def transform(self, **kwargs):
        return self

    def reshape(self, *new_shape, **kwargs):
        """

        Parameters
        ----------
        new_shape : tuple of ints or None
        kwargs

        Returns
        -------

        """
        placeholder_orbit = self.transform(to='field').copy().transform(to='modes')

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
            return placeholder_orbit.transform(to=self.basis)

    def transform(self, return_array=False, to=None):
        """ Method that handles all basis transformations.

        Parameters
        ----------
        inplace : bool
        Whether or not to return a new Orbit instance, or overwrite self.
        to : str
        The basis to transform into.

        Returns
        -------

        """
        return None

    def dae(self, *args, **kwargs):
        """ The governing equations evaluated using the current state.

        Returns
        -------
        Orbit
        """
        return None

    def residual(self, dae=True):
        """ The value of the cost function

        Returns
        -------
        float :
            The value of the cost function, equal to 1/2 the squared L_2 norm of the spatiotemporal mapping,
            R = 1/2 ||F||^2. The current form generalizes to any equation.
        """
        if dae:
            v = self.transform(to='modes').dae().state.ravel()
        else:
            v = self.state.ravel()

        return 0.5 * v.dot(v)

    def matvec(self, other, **kwargs):
        """ Matrix-vector product of a vector with the Jacobian of the current state.
        """
        return None

    def rmatvec(self, other, **kwargs):
        """ Matrix-vector product of a vector with the adjoint of the Jacobian of the current state.

        Parameters
        ----------
        other : Orbit
            Orbit whose state represents the vector in the matrix-vector product.
        Returns
        -------
        orbit_rmatvec :
            OrbitKS with values representative of the adjoint-vector product

        Notes
        -----
        The adjoint vector product in this case is defined as J^T * v,  where J is the jacobian matrix.
        """

        return None

    def state_vector(self):
        """ Vector representation of orbit"""
        return np.concatenate((self.state.ravel(), self.parameters), axis=0)

    def from_numpy_array(self, state_array, **kwargs):
        """ Utility to convert from numpy array to orbithunter format for scipy wrappers.

        Notes
        -----
        Takes a ndarray of the form of state_vector method and returns Orbit instance.
        """
        return None

    def increment(self, other, step_size=1, **kwargs):
        """ Incrementally add Orbit instances together

        Parameters
        ----------
        other : OrbitKS
            Represents the values to increment by.
        step_size : float
            Multiplicative factor which decides the step length of the correction.

        Returns
        -------
        Orbit
            New instance which results from adding an optimization correction to self.

        Notes
        -----
        This is used primarily in optimization methods, e.g. adding a gradient descent step using class instances
        instead of simply arrays.
        """
        incremented_params = tuple(self_param + step_size * other_param for self_param, other_param
                                   in zip(self.parameters, other.parameters))
        return self.__class__(state=self.state+step_size*other.state, basis=self.basis,
                              parameters=incremented_params, **kwargs)

    def _pad(self, size, axis=0):
        """ Increase the size of the discretization along an axis.

        Parameters
        ----------
        size : int
            The new size of the discretization, must be an even integer
            larger than the current size of the discretization.
        axis : int
            Axis to pad along per numpy conventions.

        Returns
        -------
        OrbitKS :
            OrbitKS instance with larger discretization.

        Notes
        -----
        Function for increasing the discretization size in dimension corresponding to 'axis'.

        """

        return self

    def _truncate(self, size, axis=0):
        """ Decrease the size of the discretization along an axis

        Parameters
        -----------
        size : int
            The new size of the discretization, must be an even integer
            smaller than the current size of the discretization.
        axis : str
            Axis to truncate along per numpy conventions.

        Returns
        -------
        OrbitKS
            OrbitKS instance with larger discretization.
        """
        return self

    def jacobian(self, **kwargs):
        """ Jacobian matrix evaluated at the current state.
        Parameters
        ----------

        Returns
        -------
        jac_ : matrix
        2-d numpy array equalling the Jacobian matrix of the governing equations evaluated at current state.
        """
        return None

    def norm(self, order=None):
        """ Norm of spatiotemporal state via numpy.linalg.norm

        Example
        -------
        Norm of a state. Should be something like np.linalg.norm(self.state.ravel(), ord=order). The following would
        return the L_2 distance between two Orbit instances, default of NumPy linalg norm is 2-norm.
        >>> (self - other).norm()
        """
        return np.linalg.norm(self.state.ravel(), ord=order)

    @property
    def shape(self):
        """ Convenience to not have to type '.state'

        Notes
        -----
        This is a property to not have to write '()' :)
        """
        return self.state.shape

    @property
    def size(self):
        """ Convenience to not have to type '.state'

        Notes
        -----
        This is a property to not have to write '()' :)
        """
        return self.state.size

    @property
    def parameters(self):
        """ Parameters required to specify a solution

        Returns
        -------

        """
        return 0.,

    @property
    def field_shape(self):
        """ Shape of field

        Returns
        -------

        """
        return 0,

    @property
    def dimensions(self):
        """ Continuous dimension extents.

        Returns
        -------

        """
        return 0.,

    @staticmethod
    def parameter_labels():
        """ Strings to use to label dimensions/periods
        """
        return 'T',

    @staticmethod
    def dimension_labels():
        """ Strings to use to label dimensions/periods
        """
        return 'T',

    @classmethod
    def glue_parameters(cls, parameter_dict_with_bundled_values, axis=0):
        """ Class method for handling parameters in gluing

        Parameters
        ----------
        parameter_dict_with_bundled_values
        axis

        Returns
        -------

        Notes
        -----
        Only required if gluing module is to be used. In the gluing process, we must have a rule for how to combine
        the fields and how to approximate the dimensions of the newly glued field. This method approximates
        with simple summation and averaging. Should accomodate any dimension via zipping parameter dict values
        in the correct manner.

        """
        new_parameter_dict = {}
        return new_parameter_dict

    def plot(self, show=True, save=False, padding=True, fundamental_domain=True, **kwargs):
        """ Custom plotting method using matplotlib
        """
        return None

    def precondition(self, preconditioning_parameters, **kwargs):
        """

        Parameters
        ----------
        preconditioning_parameters : dict
        Dictionary containing all relevant orbit parameters.
        kwargs

        Returns
        -------

        Notes
        -----
        If no preconditioning is desired then pass preconditioning=False to numerical methods, or simply return
        self as is written here.

        """
        return None

    def rescale(self, magnitude, return_array=False):
        """ Scalar multiplication

        Parameters
        ----------
        num : float
            Scalar value to rescale by.

        Notes
        -----
        This rescales the physical field such that the absolute value of the max/min takes on a new value
        of magnitude
        """
        return None

    def to_h5(self, filename=None, directory='local', verbose=False, include_residual=False):
        """ Export current state information to HDF5 file

        Parameters
        ----------
        filename : str
            Name for the save file
        directory :
            Location to save at
        verbose : If true, prints save messages to std out
        """
        if filename is None:
            filename = self.parameter_dependent_filename()

        if directory == 'local':
            directory = os.path.abspath(os.path.join(__file__, '../../data/local/', str(self)))
        elif directory == '':
            pass
        elif not os.path.isdir(directory):
            raise OSError('Trying to write to directory that does not exist. {}'.format(directory))

        save_path = os.path.abspath(os.path.join(directory, filename))
        if verbose:
            print('Saving data to {}'.format(save_path))

        # Undefined (scalar) parameters will be accounted for by __getattr__
        with h5py.File(save_path, 'w') as f:
            # The velocity field.
            f.create_dataset("field", data=self.transform(to='field').state)
            # The parameters required to exactly specify an orbit.
            f.create_dataset('parameters', data=tuple(float(p) for p in self.parameters))
            # This isn't ever actually used for KSE, just saved in case the file is to be inspected.
            f.create_dataset("discretization", data=self.field_shape)
            if include_residual:
                # This is included as a conditional statement because it seems strange to make importing/exporting
                # dependent upon full implementation of the governing equations; i.e. perhaps the equations
                # are still in development and data is used to test their implementation. In that case you would
                # not be able to export data which is undesirable.
                f.create_dataset("residual", data=float(self.residual()))
        return None

    def parameter_dependent_filename(self, extension='.h5', decimals=3):
        if self.dimensions is not None:
            dimensional_string = ''.join(['_'+''.join([self.dimension_labels()[i], str(d).split('.')[0],
                                                       'p', str(d).split('.')[1][:decimals]])
                                          for i, d in enumerate(self.dimensions) if d not in [0., 0]])
        else:
            dimensional_string = ''
        return ''.join([self.__class__.__name__, dimensional_string, extension])

    def verify_integrity(self):
        """ Check the status of a solution, whether or not it converged to the correct orbit type. """
        return None

    def _parse_state(self, state, basis, **kwargs):
        """ Determine state shape parameters based on state array and the basis it is in.

        Parameters
        ----------
        state : ndarray
        Numpy array containing state information, can have any number of dimensions.
        basis :
        The basis that the array 'state' is assumed to be in.
        kwargs

        Returns
        -------

        """
        self.state = state
        self.basis = basis
        return None

    def _parse_parameters(self, parameters, **kwargs):
        """ Determine the dimensionality and symmetry parameters.
        """
        # default is not to be constrained in any dimension;
        self.constraints = kwargs.get('constraints', {dim_key: False for dim_key, dim_val
                                                      in zip(self.dimension_labels(), self.dimensions)})
        return None

    def _random_initial_condition(self, parameters, **kwargs):
        """ Initial a set of random spatiotemporal Fourier modes
        Parameters
        ----------

        Returns
        -------
        Orbit :
        -----

        """
        return None

    def to_fundamental_domain(self, **kwargs):
        """ Placeholder for symmetry subclassees"""
        return self

    def from_fundamental_domain(self, **kwargs):
        """ Placeholder for symmetry subclassees"""
        return self

    def copy(self):
        """ Returns a shallow copy of an orbit instance.

        Returns
        -------
        Orbit :
        """
        return None


def convert_class(orbit, class_generator, **kwargs):
    """ Utility for converting between different classes.

    Parameters
    ----------
    orbit : Instance of OrbitKS or any of the derived classes.
        The orbit instance to be converted
    new_type : str or class object (not an instance).
        The target class that orbit will be converted to.

    Returns
    -------

    Notes
    -----
    To avoid conflicts with projections onto invariant subspaces, the orbit is always transformed into field
    prior to conversion; the default basis to return is the basis of the input.

    """
    return class_generator(state=orbit.transform(to='field').state, basis='field',
                           parameters=kwargs.pop('parameters', orbit.parameters), **kwargs).transform(to=orbit.basis)
