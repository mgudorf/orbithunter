import gudhi as gh
import matplotlib.pyplot as plt
import inspect
import numpy as np
from gudhi.hera import wasserstein_distance, bottleneck_distance

__all__ = ["orbit_complex", "orbit_persistence", "persistence_plot", "persistence_distance"]


def orbit_complex(orbit_instance, **kwargs):
    """
    Wrapper for Gudhi persistent homology package's PeriodicCubicalComplex

    Parameters
    ----------
    orbit_instance : Orbit
        The orbit for which to compute the complex.
    kwargs :
        `periodic_dimensions : tuple`
        Contains bools which flag which axes of the orbit's field are assumed to be periodic for the persistence
        calculations. Defaults to Orbit defaults.

    Returns
    -------
    cubical_complex : PeriodicCubicalComplex

    """
    periodic_dimensions = kwargs.get(
        "periodic_dimensions", orbit_instance.periodic_dimensions()
    )
    cubical_complex = gh.PeriodicCubicalComplex(
        dimensions=orbit_instance.state.shape,
        top_dimensional_cells=orbit_instance.state.ravel(),
        periodic_dimensions=periodic_dimensions,
    )
    return cubical_complex


def orbit_persistence(orbit_instance, **kwargs):
    """
    Evaluate the persistence of an orbit complex; returns betti numbers and persistence intervals.

    Parameters
    ----------
    orbit_instance : Orbit

    Returns
    -------
    ndarray or list :
        NumPy or Gudhi format. Numpy format returns an array of shape (N, 3). Gudhi format is a list whose elements
        are of the form (int, (float, float)).
    kwargs :
        `min_persistence : float`
        Minimum persistence interval size for returned values.
        `periodic_dimensions : tuple of bool`
        Flags the dimensions of Orbit.state which are periodic.

    Notes
    -----
    Mainly a convenience function because of how Gudhi structures its output.

    """
    # homology coeff field not supported for now
    persistence_kwargs = {
        "min_persistence": kwargs.get("min_persistence", 0.0)
    }
    # Keyword arguments for orbit_complex.
    complex_kwargs = {
        "periodic_dimensions": kwargs.get(
            "periodic_dimensions", orbit_instance.periodic_dimensions()
        )
    }
    opersist = orbit_complex(orbit_instance, **complex_kwargs).persistence(
        **persistence_kwargs
    )
    if kwargs.get("persistence_format", "numpy") == "numpy":
        return np.array([[x[0], x[1][0], x[1][1]] for x in opersist])
    else:
        return opersist


def persistence_plot(orbit_instance, gudhi_method="diagram", **kwargs):
    """
    Parameters
    ----------
    orbit_instance : Orbit
        Iterable of length N that contains elements of length 2 (i.e. N x 2 array) containing the persistence intervals
        (birth, death)
    gudhi_method : str
        Plotting gudhi_method. Takes one of the following values: 'diagram', 'barcode', 'density'.
    kwargs :
        kwargs related to gudhi plotting functions. See Gudhi docs for details.

    """
    # Get the persistence
    opersist = orbit_persistence(orbit_instance, **{**kwargs, "persistence_format": "gudhi"})
    # Pass the kwargs accepted by Gudhi for plotting
    plot_kwargs = {
        k: v
        for k, v in kwargs.items()
        if k in inspect.getfullargspec(gh.plot_persistence_diagram).args
    }
    if gudhi_method in ["diagram", "barcode", "density"]:
        gh.plot_persistence_diagram(opersist, **plot_kwargs)
    else:
        raise ValueError("Gudhi plotting gudhi_method not recognized.")
    plt.show()


def persistence_distance(orbit1, orbit2, gudhi_metric="bottleneck", **kwargs):
    """
    Compute the distance between two Orbits' persistence diagrams.

    Parameters
    ----------
    orbit1 : Orbit
        Orbit whose persistence creates the first diagram
    orbit2 : Orbit
        Orbit whose persistence creates the second diagram
    gudhi_metric : str
        The persistence diagram distance metric to use. Takes values 'bottleneck' and 'wasserstein'.
    kwargs :
        Keyword arguments for orbit persistence and orbit complex computations.

    Returns
    -------

    """
    # Get the persistences
    diagram1 = orbit_persistence(orbit1, **kwargs)[:, 1:]
    diagram2 = orbit_persistence(orbit2, **kwargs)[:, 1:]

    # Calculate the distance metric.
    if gudhi_metric == "bottleneck":
        distance_func = bottleneck_distance
    elif gudhi_metric == "wasserstein":
        distance_func = wasserstein_distance
    else:
        raise ValueError(f"{gudhi_metric} not recognized as gudhi metric.")
    return distance_func(diagram1, diagram2)


