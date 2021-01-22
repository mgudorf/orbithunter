from json import dumps
import h5py
import numpy as np
from itertools import zip_longest

__all__ = ['Orbit', 'convert_class']

"""
The core class for all orbithunter calculations. The methods listed are the ones used in the other modules. If
full functionality isn't currently desired then I recommend only implementing the methods used in optimize.py,
saving data to disk, and plotting. Of course this is in addition to the dunder methods such as __init__. 

While not listed here explicitly, this package is fundamentally a (pseudo)spectral method based package; while it is not
technically required to use a spectral method, not doing so may result in awkwardly named attributes. For example,
the resize method in spectral space essentially interpolates via zero-padding and truncation. Therefore, other
interpolation methods would be forced to use _pad and _truncate, unless they specifically overwrite the resize
method itself. Previous the labels on the bases were static but now everything is written such that they
can be accessed by an equation specific staticmethod .bases(). For the KSe this returns the tuple 
self.bases()--------->('field', 'spatial_modes', 'modes'), for example.
 
The implementation of this template class, Orbit, implements all numerical computations trivially; in other words,
the "associated equation" for this class is the trivial equation f=0, such that for any state the DAEs evaluate
to 0, the corresponding matrix vector products return zero, the Jacobian matrices are just appropriately sized
calls of np.zeros, etc. The idea is simply to implement the methods required for the numerical methods,
clipping, gluing, optimize, etc. Of course, in this case, all states are "solutions" and so any operations 
to the state doesn't *actually* do anything in terms of the "equation". The idea behind 
returning instances or arrays filled with zeros is to allow for debugging without having to complete everything
first; although one might argue *not* including the attributes/methods ensure that the team/person creating the module
does not forget anything. 

All transforms should be wrapped by
the method .transform(), such that transforming to another basis can be accessed by statements such as 
.transform(to='modes'). NOTE: if the orbit is in the same basis as that specified by 'to', the ORIGINAL orbit;
NOT a copy be returned. The reason why this is allowed is because transform then has the dual
functionality of ensuring an orbit is a certain basis for a calculation, while maintaining flexibility. There
are instances where it is required to be in the spatiotemporal basis, to avoid unanticipated transforms, however,
there are a number of operations which require the spatiotemporal basis, but often one wants to remain in the
physical basis. Therefore, to avoid verbosity, the user can specify the function self.method() instead of
self.transform(to='required_basis').method().transform(to='original_basis').  

In order for all numerical methods to work, the mandatory methods compute the matrix-vector products rmatvec = J^T * x,
matvec = J * x, and must be able to construct the Jacobian = J. ***NOTE: the matrix vector products SHOULD NOT
explicitly construct the Jacobian matrix. In the context of DAE's there is typically no need to write these
with finite difference approximations of time evolved Jacobians. (Of course if the DAEs are defined
in terms of finite differences, so should the Jacobian).***
"""


class Orbit:

    def __init__(self, state=None, basis=None, parameters=None, **kwargs):
        """ Base/Template class for orbits

        Parameters
        ----------
        state : ndarray, default None
            If an array, it should contain the state values congruent with the 'basis' argument.
        basis : str, default None
            Which basis the array 'state' is currently in.
        parameters : tuple, default None
            Parameters required to uniquely define the Orbit.
        **kwargs :
            Extra arguments for _parse_parameters and random_state
                See the description of the aforementioned method.
                
        """
        self._parse_parameters(parameters, **kwargs)
        self._parse_state(state, basis, **kwargs)

    def __add__(self, other):
        """ Addition of Orbit state and other numerical quantity.

        Parameters
        ----------
        other : Orbit, ndarray, float, int
        """
        if issubclass(type(other), Orbit):
            summation = self.state + other.state
        else:
            summation = self.state + other

        return self.__class__(state=summation, basis=self.basis, parameters=self.parameters)

    def __radd__(self, other):
        """ Addition of Orbit state and other numerical quantity.

        Parameters
        ----------
        other : Orbit, ndarray, float, int
        """
        if issubclass(type(other), Orbit):
            summation = other.state + self.state
        else:
            summation = other + self.state

        return self.__class__(state=summation, basis=self.basis, parameters=self.parameters)

    def __sub__(self, other):
        """ Subtraction of other numerical quantity from Orbit state.

        Parameters
        ----------
        other : Orbit, ndarray, float, int
        """
        if issubclass(type(other), Orbit):
            sub = self.state - other.state
        else:
            sub = self.state - other
        return self.__class__(state=sub, basis=self.basis, parameters=self.parameters)

    def __rsub__(self, other):
        """ Subtraction of Orbit state from other numeric quantity

        Parameters
        ----------
        other : Orbit, ndarray, float, int

        """
        if issubclass(type(other), Orbit):
            sub = other.state - self.state
        else:
            sub = other - self.state
        return self.__class__(state=sub, basis=self.basis, parameters=self.parameters)

    def __mul__(self, other):
        """ Multiplication of Orbit state and other numerical quantity

        Parameters
        ----------
        other : Orbit, ndarray, float, int

        Notes
        -----
        If user defined classes are not careful with shapes then accidental outer products can happen (i.e.
        array of shape (x,) * array of shape (x, 1) = array of shape (x, x)
        """
        if issubclass(type(other), Orbit):
            product = np.multiply(self.state, other.state)
        else:
            product = np.multiply(self.state, other)

        return self.__class__(state=product, basis=self.basis, parameters=self.parameters)

    def __rmul__(self, other):
        """ Multiplication of Orbit state and other numerical quantity

        Parameters
        ----------
        other : Orbit, ndarray, float, int

        Notes
        -----
        If user defined classes are not careful with shapes then accidental outer products can happen (i.e.
        array of shape (x,) * array of shape (x, 1) = array of shape (x, x)
        """
        if issubclass(type(other), Orbit):
            product = np.multiply(self.state, other.state)
        else:
            product = np.multiply(self.state, other)

        return self.__class__(state=product, basis=self.basis, parameters=self.parameters)

    def __truediv__(self, other):
        """ Division of Orbit state and other numerical quantity

        Parameters
        ----------
        other : Orbit, ndarray, float, int

        Notes
        -----
        If user defined classes are not careful with shapes then accidental outer products can happen (i.e.
        array of shape (x,) * array of shape (x, 1) = array of shape (x, x)
        """
        if issubclass(type(other), Orbit):
            quotient = np.divide(self.state, other.state)
        else:
            quotient = np.divide(self.state, other)

        return self.__class__(state=quotient, basis=self.basis, parameters=self.parameters)

    def __floordiv__(self, other):
        """ Floor division of Orbit state and other numerical quantity

        Parameters
        ----------
        other : Orbit, ndarray, float, int

        Notes
        -----
        If user defined classes are not careful with shapes then accidental outer products can happen (i.e.
        array of shape (x,) * array of shape (x, 1) = array of shape (x, x)
        """
        if issubclass(type(other), Orbit):
            quotient = np.floor_divide(self.state, other.state)
        else:
            quotient = np.floor_divide(self.state, other)
        return self.__class__(state=quotient, basis=self.basis, parameters=self.parameters)

    def __pow__(self, power):
        """ Exponentiation of Orbit state.

        Parameters
        ----------
        power : float
        """
        return self.__class__(state=self.state**power, basis=self.basis, parameters=self.parameters)

    def __str__(self):
        """ String name

        Returns
        -------
        str :
            Of the form 'Orbit'
        """
        return self.__class__.__name__

    def __repr__(self):
        """ More descriptive than __str__ using beautified parameters."""
        if self.parameters is not None:
            # parameters should be an iterable
            try:
                pretty_params = tuple(round(x, 3) if isinstance(x, float)
                                      else x for x in self.parameters)
            except TypeError:
                pretty_params = self.parameters
        else:
            pretty_params = None

        dict_ = {'shape': self.shape,
                 'basis': self.basis,
                 'parameters': pretty_params}
        # convert the dictionary to a string via json.dumps
        dictstr = dumps(dict_)
        return self.__class__.__name__ + '(' + dictstr + ')'

    def __getattr__(self, attr):
        """ Retrieve parameters, discretization variables with their labels instead of slicing 'parameters'

        Notes
        -----
        This is simply to avoid defining attributes or properties for each variable name; keep the namespace clean.
        """
        try:
            attr = str(attr)
        except ValueError:
            print('Attribute is not of readable type')

        if attr in self.parameter_labels():
            # parameters must be cast as tuple, (p,) if singleton.
            return self.parameters[self.parameter_labels().index(attr)]
        elif attr in self.discretization_labels():
            # parameters must be cast as tuple, (p,) if singleton.
            return self.discretization[self.discretization_labels().index(attr)]
        else:
            error_message = ' '.join([self.__class__.__name__, 'has no attribute\'{}\''.format(attr)])
            raise AttributeError(error_message)

    @staticmethod
    def bases():
        """ Labels of the different bases that 'state' attribute can be in.

        Notes
        -----
        Defaults to 'physical' and not None or empty string because it is used as a data group for writing .h5 files.
        """
        return ('physical',)

    @staticmethod
    def ndim():
        """ Number of expected dimensions of state array

        Notes
        -----
        Auxiliary usage is to use inherit default labels; that is, so the labels defined as staticmethods do not
        have to be repeated for derived classes.
        """
        return 4

    @staticmethod
    def parameter_labels():
        """ Strings to use to label dimensions. Generic 3+1 spacetime labels default.
        """
        return 't', 'x', 'y', 'z'

    @staticmethod
    def dimension_labels():
        """ Strings to use to label dimensions/periods; this is redundant for Orbit class.
        """
        return 't', 'x', 'y', 'z'

    @staticmethod
    def discretization_labels():
        """ Strings to use to label discretization variables. Generic 3+1 spacetime labels default.
        """
        return 'n', 'i', 'j', 'k'

    @classmethod
    def default_parameter_ranges(cls):
        """ Intervals (continuous) or iterables (discrete) used to generate parameters.
        Notes
        -----
        tuples or length two are *always* interpreted to be continuous intervals. If you have a discrete variable
        with two options, simply use a list instead of tuple.
        """
        return {p_label: (0, 1) for p_label in cls.parameter_labels()}

    @staticmethod
    def default_shape():
        """ The default array shape when dimensions are not specified. """
        return 1, 1, 1, 1

    @staticmethod
    def minimal_shape():
        """ The smallest possible compatible discretization for the given instance.

        Returns
        -------
        tuple of int :
            The minimal shape that the shape can take and still have numerical operations (transforms mainly)
            be compatible

        Notes
        -----
        Often symmetry constraints reduce the dimensionality; if too small this reduction may leave the state empty,
        this is used for aspect ratio correction and possibly other gluing applications.
        """
        return 1, 1, 1, 1

    @property
    def shape(self):
        """ Current state's shape

        Notes
        -----
        Just a convenience to be able to write self.shape instead of self.state.shape
        """
        return self.state.shape

    @property
    def size(self):
        """ Current state's total dimensionality

        Notes
        -----
        Just a convenience to be able to write self.sizeinstead of self.state.size
        """
        return self.state.size

    @classmethod
    def parameter_based_discretization(cls, parameters, **kwargs):
        """ Follow orbithunter conventions for discretization size.

        Parameters
        ----------
        parameters : tuple
            Values from which the discretization may be inferred.

        kwargs :
            Various flags for defining discretization; can be highly dependent on equation and so
            is left as vague as possible.

        Returns
        -------
        tuple :
            A tuple of ints
        """
        return cls.default_shape()

    @classmethod
    def glue_parameters(cls, dimension_tuples, glue_shape, non_zero=True):
        """ Class method for handling parameters in gluing

        Parameters
        ----------
        dimension_tuples : tuple of tuples

        glue_shape : tuple of ints
            The shape of the gluing being performed i.e. for a 2x2 orbit grid glue_shape would equal (2,2).
        non_zero : bool
            If True, then the calculation of average dimensions excludes 0's.

        Returns
        -------
        glued_parameters : tuple
            tuple of parameters same dimension and type as self.parameters

        Notes
        -----
        This returns an average of parameter tuples, used exclusively in the gluing method; wherein the new tile
        dimensions needs to be decided upon/inferred from the original tiles. As this average is only a very
        crude approximation, it can be worthwhile to also simply search the parameter space for a combination
        of dimensions which reduces the residual. The strategy produced by this method is simply a baseline.

        """
        if non_zero:
            return tuple(glue_shape[i] * p[p > 0.].mean() for i, p in enumerate(np.array(ptuple) for ptuple
                                                                                in dimension_tuples))
        else:
            return tuple(glue_shape[i] * p.mean() for i, p in enumerate(np.array(ptuple) for ptuple
                                                                        in dimension_tuples))

    def dimensions(self):
        """ Continuous tile dimensions

        Returns
        -------
        tuple :
            Tuple of dimensions, typically this will take the form (t, x, y, z) for (3+1)-D spacetime

        Notes
        -----
        Because this is usually a subset of self.parameters, it does not use the property decorator. This method
        is purposed for readability.
        """
        return tuple(getattr(self, d_label) for d_label in self.dimension_labels())

    def shapes(self):
        """ The different array shapes based on discretization parameters and basis.

        Returns
        -------
        tuple :
            Contains shapes of state in all bases, ordered with respect to self.bases() ordering.

        Notes
        -----
        This is a convenience function for operations which require the shape of the state array in a different basis.
        These shapes are defined by the transforms, essentially, but it is wasteful to transform simply for the shape,
        and the amount of boilerplate code to constantly infer the shape justifies this method in most cases.
        """
        return (self.state.shape,)

    def cost_function_gradient(self, eqn, **kwargs):
        """ Gradient of scalar cost functional defaults to grad * (1/2 ||eqn||^2)

        Parameters
        ----------
        eqn : Orbit
            Orbit instance whose state is an evaluation of the governing equations
        kwargs : dict
            extra arguments for rmatvec method.

        Returns
        -------
        gradient :
            Orbit instance whose state contains (dF/dv)^T * F ; (adjoint Jacobian * eqn)

        Notes
        -----
        Withing optimization routines, the eqn orbit is used for other calculations and hence should not be
        recalculated; this is why eqn is passed rather than calculated.
        """
        return self.rmatvec(eqn, **kwargs)

    def resize(self, *new_discretization, **kwargs):
        """ Rediscretization method

        Parameters
        ----------
        new_discretization : int or tuple of ints
            New discretization size
        kwargs : dict
            keyword arguments for parameter_based_discretization.

        Returns
        -------
        placeholder_orbit :
            Orbit with new discretization; the new shape always refers to the shape in the self.bases()[0] basis.
            Always returned in originating basis.

        Notes
        -----
        # These cases covered by unpacking tuples of length 1.
        If passed as single int x, then new_discretization=(x,): len==1 but type(*new_shape)==int
        If passed as tuple with length one (a,), then new_discretization=((a,),)
        If passed as tuple with length n, then new_discretization=((x,y,...,z),)
        If len >= 2 then could be multiple ints (x,y) or multiple tuples ((a,b), (c,d))
        In other words, they are all tuples, but type checking and unpacking has to be done carefully due to contents.
        """
        # Padding basis assumed to be in the spatiotemporal basis.
        placeholder_orbit = self.copy().transform(to=self.bases()[-1])

        # if nothing passed, then new_shape == () which evaluates to false.
        # The default behavior for this will be to modify the current discretization
        # to a `parameter based discretization'.
        new_shape = new_discretization or self.parameter_based_discretization(self.parameters, **kwargs)

        # unpacking unintended nested tuples i.e. ((a, b, ...)) -> (a, b, ...); leaves unnested tuples invariant.
        # New shape must be tuple; i.e. iterable and have __len__
        if len(new_shape) == 1 and isinstance(*new_shape, tuple):
            new_shape = tuple(*new_shape)

        # If the current shape is discretization size (not current shape) differs from shape then resize
        if self.discretization != new_shape:
            # Although this is less efficient than doing every axis at once, it generalizes to cases where bases
            # are different for padding along different dimensions (i.e. transforms implicit in truncate and pad).
            # Changed from iterating over new shape and comparing with old, to iterating over old and comparing
            # with new; this prevents accidentally
            for i, d in enumerate(self.discretization):
                if new_shape[i] < d:
                    placeholder_orbit = placeholder_orbit.truncate(d, axis=i)
                elif new_shape[i] > d:
                    placeholder_orbit = placeholder_orbit.pad(d, axis=i)
                else:
                    pass

        return placeholder_orbit.transform(to=self.basis)

    def transform(self, to=None):
        """ Method that handles all basis transformations. Undefined for Orbit class.

        Parameters
        ----------
        to : str
            The basis to transform into. If already in said basis, returns self. Default written here as '', but
            can of course be changed to suit the equations.

        Returns
        -------
        Orbit :
            either self or instance in new basis. Returning self and not copying may have unintended consequences
            but typically it would not matter as orbithunter avoids overwrites.
        """
        return self

    def eqn(self, *args, **kwargs):
        """ The governing equations evaluated using the current state.

        Returns
        -------
        Orbit :
            Orbit instance whose state equals evaluation of governing equation.

        Notes
        -----
        If self.eqn().state = 0. at every point (within some numerical tolerance), then the state constitutes
        a solution to the governing equation. Of course there is no equation for this class, so zeros are returned.
        The instance needs to be in spatiotemporal basis prior to computation; this avoids possible mistakes in the
        optimization process, which would result in a breakdown in performance from redundant transforms.
        """
        assert self.basis == self.bases()[-1], 'Convert to spatiotemporal basis before computing governing equations.'
        return self.__class__(state=np.zeros(self.shapes()[-1]), basis=self.bases()[-1], parameters=self.parameters)

    def residual(self, eqn=True):
        """ Cost function evaluated at current state.

        Returns
        -------
        float :
            The value of the cost function, equal to 1/2 the squared L_2 norm of the spatiotemporal mapping,
            R = 1/2 ||F||^2. The current form generalizes to any equation.

        Notes
        -----
        In certain optimization methods, it is more efficient to have the DAEs stored, and then take their norm
        as opposed to re-evaluating the DAEs. The reason why .norm() isn't called instead is to allow for different
        residual functions other than, for instance, the L_2 norm of the DAEs; although in this case there is no
        difference.
        """
        if eqn:
            v = self.transform(to=self.bases()[-1]).eqn().state.ravel()
        else:
            v = self.state.ravel()
        return 0.5 * v.dot(v)

    def matvec(self, other, **kwargs):
        """ Matrix-vector product of Jacobian evaluated at instance state, times vector of other instance.

        Parameters
        ----------
        other : Orbit
            Orbit whose state represents the vector in the matrix-vector product.

        Returns
        -------
        orbit_matvec :
            Orbit with values representative of the matrix-vector product

        Notes
        -----
        Because the general Orbit template doesn't have an associated equation, returns an array of zeros.
        """
        return self.__class__(state=np.zeros(self.shape), basis=self.basis,
                              parameters=tuple([0] * len(self.parameter_labels())))

    def rmatvec(self, other, **kwargs):
        """ Matrix-vector product of adjoint Jacobian evaluated at instance state, times vector of other instance.

        Parameters
        ----------
        other : Orbit
            Orbit whose state represents the vector in the matrix-vector product.

        Returns
        -------
        orbit_rmatvec :
            Orbit with values representative of the adjoint-vector product
        """
        return self.__class__(state=np.zeros(self.shape), basis=self.basis,
                              parameters=tuple([0] * len(self.parameter_labels())))

    def orbit_vector(self):
        """ Vector representation of Orbit instance.

        Returns
        -------
        ndarray :
            The state vector: the current state with parameters appended, returned as a (self.size + n_params , 1)
            dimensionality for scipy purposes.
        """
        return np.concatenate((self.state.ravel(), self.parameters), axis=0).reshape(-1, 1)

    def from_numpy_array(self, orbit_vector, **kwargs):
        """ Utility to convert from numpy array (orbit_vector) to Orbit instance for scipy wrappers.

        Parameters
        ----------
        orbit_vector : ndarray
            Vector with (spatiotemporal basis) state values and parameters.

        kwargs :
            parameters : tuple
                If parameters from another Orbit instance are to overwrite the values within the orbit_vector
            parameter_constraints : dict
                constraint dictionary, keys are parameter_labels, values are bools
            Orbit or subclass kwargs : dict
                If special kwargs are required/desired for Orbit instantiation.
        Returns
        -------
        state_orbit : Orbit instance
            Orbit instance whose state and parameters are extracted from the input orbit_vector.

        Notes
        -----
        Important: If parameters are passed as a keyword argument, they are appended to the numpy array,
        'state_array', via concatenation.

        This function assumes that the instance calling it is in the "spatiotemporal" basis; the basis in which
        the optimization occurs. This is why no additional specification for size and shape and basis is required.
        """
        # slice out the parameters; cast as list to gain access to pop
        params_list = list(kwargs.pop('parameters', orbit_vector.ravel()[self.size:].tolist()))
        # The usage of this function is to convert a vector of corrections to an orbit instance;
        # while default parameter values may be None, default corrections are 0.
        parameters = tuple(params_list.pop(0) if not constrained and params_list else 0
                           for constrained in self.constraints.values())
        return self.__class__(state=np.reshape(orbit_vector.ravel()[:self.size], self.shape), basis=self.bases()[-1],
                              parameters=parameters, **kwargs)

    def increment(self, other, step_size=1, **kwargs):
        """ Incrementally add Orbit instances together

        Parameters
        ----------
        other : Orbit
            Represents the values to increment by.
        step_size : float
            Multiplicative other which decides the step length of the correction.

        Returns
        -------
        Orbit :
            New instance incremented by other instance's values. Typically self is the current iterate and
            other is the optimization correction.

        Notes
        -----
        This is used primarily in optimization methods, e.g. adding a gradient descent step using class instances
        instead of simply arrays.
        """
        incremented_params = tuple(self_param + step_size * other_param
                                   if other_param != 0 else self_param  # assumed to be constrained if 0.
                                   for self_param, other_param in zip(self.parameters, other.parameters))

        return self.__class__(state=self.state + step_size * other.state, basis=self.basis,
                              parameters=incremented_params, **kwargs)

    def pad(self, size, axis=0):
        """ Increase the size of the discretization along an axis.

        Parameters
        ----------
        size : int
            The new size of the discretization, restrictions typically imposed by equations.
        axis : int
            Axis to pad along per numpy conventions.

        Returns
        -------
        Orbit :
            Orbit instance whose state in the physical (self.bases()[0]) basis has a number of discretization
            points equal to 'size'

        Notes
        -----
        This function is typically an interpolation method, i.e. Fourier mode zero-padding.
        However, in the general case when we cannot assume the basis, the best we can do is pad the current basis,
        which is done in a symmetric fashion when possible.

        That is, if we have a 4x4 array, then calling this with size=6 and axis=0 would yield a 6x4 array, wherein
        the first and last rows are uniformly zero. I.e. a "border" of zeroes has been added. The choice to make
        this symmetric matters in the case of non-periodic boundary conditions.

        When writing this function for spectral interpolation methods BE SURE TO ACCOUNT FOR NORMALIZATION
        of your transforms. Also, in this instance the interpolation basis and the return basis are the same, as there
        is no way of specifying otherwise for the general Orbit class. For the KSe, the padding basis is 'modes'
        and the return basis is whatever the state was originally in. This is the preferred implementation.
        """
        padding_size = (size - self.shape[axis]) // 2
        if int(size) % 2:
            # If odd size then cannot distribute symmetrically, floor divide then add append extra zeros to beginning
            # of the dimension.
            padding_tuple = tuple((padding_size + 1, padding_size) if i == axis else (0, 0)
                                  for i in range(len(self.shape)))
        else:
            padding_tuple = tuple((padding_size, padding_size) if i == axis else (0, 0)
                                  for i in range(len(self.shape)))

        return self.__class__(state=np.pad(self.state, padding_tuple), basis=self.basis,
                              parameters=self.parameters).transform(to=self.basis)

    def truncate(self, size, axis=0):
        """ Decrease the size of the discretization along an axis

        Parameters
        -----------
        size : int
            The new size of the discretization, must be an even integer
            smaller than the current size of the discretization.
        axis : int
            Axis to truncate along per numpy conventions.

        Returns
        -------
        Orbit
            Orbit instance with smaller discretization.

        Notes
        -----
        The inverse of pad. Default behavior is to simply truncate in current basis in symmetric fashion along
        axis of numpy array specific by 'axis'.
        """
        truncate_size = (self.shape[axis] - size) // 2
        if int(size) % 2:
            # If odd size then cannot distribute symmetrically, floor divide then add append extra zeros to beginning
            # of the dimension.
            truncate_slice = tuple(slice(truncate_size + 1, -truncate_size) if i == axis else slice(None)
                                   for i in range(len(self.shape)))
        else:
            truncate_slice = tuple(slice(truncate_size, -truncate_size) if i == axis else slice(None)
                                   for i in range(len(self.shape)))

        return self.__class__(state=self.state[truncate_slice], basis=self.basis,
                              parameters=self.parameters).transform(to=self.basis)

    def jacobian(self, **kwargs):
        """ Jacobian matrix evaluated at the current state.

        Parameters
        ----------
        kwargs :
            Included in signature for derived classes; no usage here.
        Returns
        -------
        jac_ : matrix
            2-d numpy array equalling the Jacobian matrix of the governing equations evaluated at current state.
        """
        return np.zeros([self.size, self.orbit_vector().size])

    def norm(self, order=None):
        """ Norm of spatiotemporal state via numpy.linalg.norm
        """
        return np.linalg.norm(self.state.ravel(), ord=order)

    def plot(self, show=True, save=False, padding=True, fundamental_domain=True, **kwargs):
        """ Signature for plotting method.
        """
        return None

    def rescale(self, magnitude, method='inf'):
        """ Rescaling of the state in the 'physical' basis per strategy denoted by 'method'
        """
        state = self.transform(to=self.bases()[0]).state
        if method == 'inf':
            rescaled_state = magnitude * state / np.max(np.abs(state.ravel()))
        elif method == 'L1':
            rescaled_state = magnitude * state / np.linalg.norm(state, ord=1)
        elif method == 'L2':
            rescaled_state = magnitude * state / np.linalg.norm(state)
        elif method == 'power':
            rescaled_state = np.sign(state) * np.abs(state) ** magnitude
        else:
            raise ValueError('Unrecognizable method.')
        return self.__class__(state=rescaled_state, basis=self.bases()[0],
                              parameters=self.parameters).transform(to=self.basis)

    def to_h5(self, filename=None, orbit_name=None, h5py_mode='r+', verbose=False, include_residual=False):
        """ Export current state information to HDF5 file

        Parameters
        ----------
        filename : str, default None
            filename to write/append to.
        orbit_name : str, default None
            Name of the orbit_name wherein to store the Orbit in the h5_file at location filename. Should be
            HDF5 group name, i.e. '/A/B/C/...'
        h5py_mode : str
            Mode with which to open the file. Default is a, read/write if exists, create otherwise,
            other modes ['r+', 'a', 'w-', 'w']. See h5py.File for details. 'r' not allowed, because this is a function
            to write to the file. Defaults to r+ to prevent overwrites.
        verbose : bool
            Whether or not to print save location and group
        include_residual : bool
            Whether or not to include residual as a dataset; requires equation to be well-defined for current instance.
        """
        if verbose:
            print('Saving data to {} under group name'.format(filename, orbit_name))

        try:
            with h5py.File(filename, h5py_mode) as f:
                # Returns orbit_name if not None, else, filename method.
                orbit_group = f.require_group(orbit_name or self.filename(extension=''))
                # State may be empty, but can still save.
                orbit_group.create_dataset(self.bases()[0], data=self.transform(to=self.bases()[0]).state)
                # The parameters required to exactly specify an orbit.
                orbit_group.create_dataset('parameters', data=tuple(float(p) for p in self.parameters))
                if include_residual:
                    # This is included as a conditional statement because it seems strange to make importing/exporting
                    # dependent upon full implementation of the governing equations; i.e. perhaps the equations
                    # are still in development and data is used to test their implementation. In that case you would
                    # not be able to export data which is undesirable.
                    try:
                        orbit_group.create_dataset('residual', data=float(self.residual()))
                    except (ZeroDivisionError, ValueError):
                        print('Unable to compute residual for {}'.format(repr(self)))
        except (OSError, IOError):
            print('unable to write orbit data to .h5 file.')

    def filename(self, extension='.h5', decimals=3):
        """ Method for consistent/conventional filenaming. High dimensions will yield long filenames.

        Parameters
        ----------
        extension : str
            The extension to append to the filename
        decimals :
            The number of decimals to include in the str name of the orbit.

        Returns
        -------
        str :
            The conventional filename.
        """
        if self.dimensions() is not None:
            dimensional_string = ''.join(['_' + ''.join([self.dimension_labels()[i],
                                                         str(round(d, decimals)).replace('.', 'p')])
                                          for i, d in enumerate(self.dimensions()) if (d != 0) and (d is not None)])
        else:
            dimensional_string = ''
        return ''.join([self.__class__.__name__, dimensional_string, extension])

    def verify_integrity(self):
        """ Check the status of a solution, whether or not it converged to the correct orbit type. """
        return self

    def generate(self, attr='all', **kwargs):
        """ Initialize random parameters or state or both.

        Parameters
        ----------
        attr : str
            Takes values 'state', 'parameters' or 'all'.

        Notes
        -----
        Produces a random state and or parameters depending on 'attr' value.
        """
        if attr in ['all', 'parameters']:
            self._generate_parameters(**kwargs)

        if attr in ['all', 'state']:
            self._generate_state(**kwargs)
        # For chaining operations, return self instead of None
        return self

    def to_fundamental_domain(self, **kwargs):
        """ Placeholder/signature for possible symmetry subclasses. """
        return self

    def from_fundamental_domain(self, **kwargs):
        """ Placeholder/signature for possible symmetry subclasses. """
        return self

    def copy(self):
        """ Return an instance with deep copy of numpy array. """
        return self.__class__(state=self.state.copy(), parameters=self.parameters, basis=self.basis)

    def constrain(self, *labels):
        """ Set self constraints based on labels provided.

        Parameters
        ----------
        labels : str or tuple of str
        """
        if isinstance(labels, str):
            labels = (labels,)
        elif not isinstance(labels, tuple):
            raise TypeError('constraint labels must be str or tuple of str')
        # Maintain other constraints when constraining.
        constraints = {key: (True if key in tuple(*labels) else False)
                       for key, val in self.constraints.items()}
        setattr(self, 'constraints', constraints)

    def _parse_state(self, state, basis, **kwargs):
        """ Determine state and state shape parameters based on state array and the basis it is in.

        Parameters
        ----------
        state : ndarray
            Numpy array containing state information, can have any number of dimensions.
        basis : str
            The basis that the array 'state' is assumed to be in.
        """
        # Initialize with the same amount of dimensions as labels; use labels because staticmethod.
        # The 'and-or' trick; if state is None then latter is used. give empty array the expected number of
        # dimensions, even though array with 0 size in dimensions will typically be flattened by NumPy anyway.
        if isinstance(state, np.ndarray):
            self.state = state
        elif state is None:
            self.state = np.array([], dtype=float).reshape(len(self.default_shape()) * [0])
        else:
            raise ValueError('"state" attribute may only be provided as NumPy array or None.')

        if self.size > 0:
            # This seems redundant but typically the discretization needs to be inferred from the state
            # and the basis; as the number of variables is apt to change when symmetries are taken into account.
            self.basis = basis
            self.discretization = self.state.shape
            if basis is None:
                raise ValueError('basis must be provided when state is provided')
        else:
            self.discretization = None
            self.basis = None

    def _parse_parameters(self, parameters, **kwargs):
        """ Parse and initialize the set of parameters

        Notes
        -----
        Parameters are required to be numerical in type. If there are categorical parameters then they
        should be assigned to a different attribute. The reason for this is that for numerical optimization,
        the orbit_vector; the concatenation of self.state and self.parameters is sent to the various algorithms.
        Cannot send categoricals to these algorithms.

        """
        # default is not to be constrained in any dimension;
        self.constraints = kwargs.get('constraints', {dim_key: False for dim_key in self.parameter_labels()})
        if parameters is None:
            self.parameters = parameters
        elif isinstance(parameters, tuple):
            # This ensures all parameters are filled. If unequal in length, zip truncates
            # If more parameters than labels then we do not know what to call them by; truncate.
            if len(self.parameter_labels()) < len(parameters):
                self.parameters = tuple(val for label, val in zip(self.parameter_labels(), parameters))
            else:
                # if more labels than parameters, simply fill with the default missing value, 0.
                self.parameters = tuple(val for label, val in zip_longest(self.parameter_labels(), parameters,
                                                                          fillvalue=0))
        else:
            # A number of methods require parameters to be an iterable, hence the tuple requirement.
            raise TypeError('"parameters" is required to be a tuple or None. '
                            'singleton parameter "p" needs to be cast as tuple (p,).')

    def _generate_parameters(self, **kwargs):
        """ Randomly initialize parameters which are currently zero.

        Parameters
        ----------
        kwargs :
            p_ranges : dict
                keys are parameter_labels, values are uniform sampling intervals or iterables to sample from

        """
        # helper function so comprehension can be used later on; each orbit type typically has a default
        # range of good parameters; however, it is often the case that using a user-defined range is desired.
        def sample_from_generator(val, val_generator, overwrite=False):
            if val == 0 or overwrite:
                # for numerical parameter generators we're going to use uniform distribution to generate values
                # If the generator is "interval like" then use uniform distribution.
                if isinstance(val_generator, tuple) and len(val_generator) == 2:
                    pmin, pmax = val_generator
                    val = pmin + (pmax - pmin) * np.random.rand()
                # Everything else treated as distribution to sample from
                else:
                    val = np.random.choice(val_generator)
            return val

        # seeding takes a non-trivial amount of time, only set if explicitly provided.
        if isinstance(kwargs.get('seed', None), int):
            np.random.seed(kwargs.get('seed', None))

        # Can be useful to override default sample spaces to get specific cases.
        p_ranges = kwargs.get('parameter_ranges', self.default_parameter_ranges())
        # If *some* of the parameters were initialized, we want to save those values; iterate over the current
        # parameters if not None, else,
        parameter_iterable = self.parameters or len(self.parameter_labels()) * [0]
        if len(self.parameter_labels()) < len(parameter_iterable):
            # If more values than labels, then truncate and discard the additional values
            parameters = tuple(sample_from_generator(val, p_ranges[label], overwrite=kwargs.get('overwrite', False))
                               for label, val in zip(self.parameter_labels(), parameter_iterable))
        else:
            # If more labels than parameters, fill the missing parameters with default
            parameters = tuple(sample_from_generator(val, p_ranges[label], overwrite=kwargs.get('overwrite', False))
                               for label, val in zip_longest(self.parameter_labels(), parameter_iterable, fillvalue=0))
        setattr(self, 'parameters', parameters)

    def _generate_state(self, **kwargs):
        """ Populate the 'state' attribute

        Parameters
        ----------
        kwargs

        Notes
        -----
        Must generate and set attributes 'state', 'discretization' and 'basis'. The state is required to be a numpy
        array, the discretization is required to be its shape (tuple) in the basis specified by self.bases()[0].
        Discretization is coupled to the state and its specific basis, hence why it is generated here.

        Historically, for the KSe, the strategy to define a specific state was to provide a keyword argument 'spectrum'
        which controlled a spectrum modulation strategy. This is not included in the base signature, because it is
        terminology specific to spectral methods.
        """
        # Just generate a random array; more intricate strategies should be written into subclasses.
        # Using standard normal distribution for values.
        numpy_seed = kwargs.get('seed', None)
        if isinstance(numpy_seed, int):
            np.random.seed(numpy_seed)
        # Presumed to be in physical basis unless specified otherwise.
        self.discretization = self.parameter_based_discretization(self.parameters, **kwargs)
        self.state = np.random.randn(*self.discretization)
        self.basis = kwargs.get('basis', None) or self.bases()[0]


def convert_class(orbit, class_generator, **kwargs):
    """ Utility for converting between different classes.

    Parameters
    ----------
    orbit : Orbit instance
        The orbit instance to be converted
    class_generator : class generator
        The target class that orbit will be converted to.

    Notes
    -----
    To avoid conflicts with projections onto symmetry invariant subspaces, the orbit is always transformed into the
    physical basis prior to conversion; the instance is returned in the basis of the input, however.

    """
    return class_generator(state=orbit.transform(to=orbit.bases()[0]).state, basis=orbit.bases()[0],
                           parameters=kwargs.pop('parameters', orbit.parameters), **kwargs).transform(to=orbit.basis)
