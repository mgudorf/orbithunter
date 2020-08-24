# orbithunter : framework for solving spatiotemporal partial differential equations

 [orbithunter github](https://github.com/mgudorf/orbithunter/) to maintain and preview the content for your website in Markdown files.

# Introduction 

This project is an accumulation (and heavy refactoring) of [Matthew Gudorf's](https://www.linkedin.com/in/mgudorf/) 
research code developed while pursuing his Physics PhD. from Georgia Tech. This package was developed primarily for the study of
the spatiotemporal [Kuramoto-Sivashinsky equation](https://en.wikipedia.org/wiki/Kuramoto%E2%80%93Sivashinsky_equation). 

The main goal of this project is to create a foundation that anyone can use to solve and explore nonlinear, spatiotemporal and chaotic
partial differential equations. The project was motivated by the observation that many people have written code to do the same thing; solve
the Kuramoto-Sivashinsky equation as a exponentially unstable dynamical system. This is inefficient as (in my experience) everyone writes
their own code instead of having access to an open source project. The whole point of my thesis is that time dynamical codes are exponentially
unstable and hence the problem of studying the Kuramoto-Sivashinsky equation as a first order in time partial differential equation is **ill-posed**.
By solving the equation spatiotemporally using a (1+1) dimensional spacetime Fourier basis, we can find infinitely many unstable periodic orbits very
efficiently, ***without any a priori knowledge of the equations or the code***. 
In other words, I have developed this package to be as user friendly as possible, while still maintaining computational efficiency, relative to the older
versions of my research code. 

# Notes on readability and computational efficiency. 

The current code is suboptimal in regards to computation speed because I maximize readability as opposed to pure computational speed. If I was going for
speed I shouldn't really be using Python anyway. The more efficient branch primarily used class instances as a means of bundling NumPy arrays
with parameters. The code becomes extraordinarily more readable if a small sacrifice to speed is made, however. 
This is easily achieved by replacing the NumPy array oriented field derivative computations with the default ```orbithunter``` derivative methods,
chosen to return NumPy arrays. This way, the number of instantiated class instances is kept down, but the derivative computations are contained within
the very succinct .dx() and .dt() methods. 

A preliminary benchmark yielded the following computation times for each version of the code

| Branch  | Total time (s)  | Time per descent step (s) |
|---|---|---|
| Research code  | 54.37  | 0.00166  |
| Verbose branch  |  33.73 | 0.00102  |
| Succinct branch  |  38.10 | 0.00116  |

Only the user can really determine if this was worth it or not. Here is an example of the code in its verbose, more efficient form vs. succinct, less efficient
form.

## Code refactoring example (Comments removed for comparison purposes)

### Verbose form 
```markdown
      assert self.state_type == 'modes', 'Convert to spatiotemporal Fourier mode basis before computations.'
      modes = self.state
      elementwise_dt = self.elementwise_dtn(self.parameters)
      elementwise_dx2 = self.elementwise_dxn(self.parameters, power=2)
      elementwise_dx4 = self.elementwise_dxn(self.parameters, power=4)

      dt = swap_modes(np.multiply(elementwise_dt, modes), dimension='time')
      dx2 = np.multiply(elementwise_dx2, modes)
      dx4 = np.multiply(elementwise_dx4, modes)
      linear_modes = dt + dx2 + dx4
      orbit_field = self.convert(to='field')
      nonlinear_modes = orbit_field.pseudospectral(orbit_field).state

      mapping_modes = linear_modes + nonlinear_modes
      return self.__class__(state=mapping_modes, state_type='modes', T=self.T, L=self.L)
```
### Succinct form 
```markdown
    assert self.state_type == 'modes', 'Convert to spatiotemporal Fourier mode basis before computations.'
    orbit_field = self.convert(to='field')
    mapping_modes = (self.dt(return_modes=True) + self.dx(power=2, return_modes=True)
                     + self.dx(power=4, return_modes=True)
                     + orbit_field.pseudospectral(orbit_field, return_modes=True))
    return self.__class__(state=mapping_modes, state_type='modes', T=self.T, L=self.L)
```
