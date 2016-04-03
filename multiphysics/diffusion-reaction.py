"""
solve a scalar diffusion-reaction equation:

 phi_t = kappa phi_{xx} + (1/tau) R(phi)

using operator splitting, with implicit diffusion

M. Zingale
"""

from __future__ import print_function

import numpy as np
from scipy import linalg
from scipy.integrate import ode
import sys
import matplotlib.pyplot as plt

def frhs(t, phi, tau):
    """ reaction ODE righthand side """
    return 0.25*phi*(1.0 - phi)/tau

def jac(t, phi):
    return None

def react(gr, phi, tau, dt):
    """ react phi through timestep dt """

    phinew = gr.scratch_array()

    for i in range(gr.ilo, gr.ihi+1):
        r = ode(frhs,jac).set_integrator("vode", method="adams",
                                         with_jacobian=False)
        r.set_initial_value(phi[i], 0.0).set_f_params(tau)
        r.integrate(r.t+dt)
        phinew[i] = r.y[0]

    return phinew

def diffuse(gr, phi, kappa, dt):
    """ diffuse phi implicitly (C-N) through timestep dt """

    phinew = gr.scratch_array()

    alpha = kappa*dt/gr.dx**2

    # create the RHS of the matrix
    R = phi[gr.ilo:gr.ihi+1] + \
        0.5*alpha*(    phi[gr.ilo-1:gr.ihi] -
                   2.0*phi[gr.ilo  :gr.ihi+1] +
                       phi[gr.ilo+1:gr.ihi+2])


    # create the diagonal, d+1 and d-1 parts of the matrix
    d = (1.0 + alpha)*np.ones(gr.nx)
    u = -0.5*alpha*np.ones(gr.nx)
    u[0] = 0.0

    l = -0.5*alpha*np.ones(gr.nx)
    l[gr.nx-1] = 0.0

    # set the boundary conditions by changing the matrix elements

    # homogeneous neumann
    d[0] = 1.0 + 0.5*alpha
    d[gr.nx-1] = 1.0 + 0.5*alpha

    # dirichlet
    #d[0] = 1.0 + 1.5*alpha
    #R[0] += alpha*0.0

    #d[gr.nx-1] = 1.0 + 1.5*alpha
    #R[gr.nx-1] += alpha*0.0

    # solve
    A = np.matrix([u,d,l])
    phinew[gr.ilo:gr.ihi+1] = linalg.solve_banded((1,1), A, R)

    return phinew

def est_dt(gr, kappa, tau):
    """ estimate the timestep """

    # use the proported flame speed
    s = np.sqrt(kappa/tau)
    dt = gr.dx/s
    return dt


class Grid(object):

    def __init__(self, nx, ng=1, xmin=0.0, xmax=1.0, vars=None):
        """ grid class initialization """

        self.nx = nx
        self.ng = ng

        self.xmin = xmin
        self.xmax = xmax

        self.dx = (xmax - xmin)/nx
        self.x = (np.arange(nx+2*ng) + 0.5 - ng)*self.dx + xmin

        self.ilo = ng
        self.ihi = ng+nx-1

        self.data = {}

        for v in vars:
            self.data[v] = np.zeros((2*ng+nx), dtype=np.float64)

    def fillBC(self, var):

        if not var in self.data.keys():
            sys.exit("invalid variable")

        vp = self.data[var]

        # Neumann BCs
        vp[0:self.ilo+1] = vp[self.ilo]
        vp[self.ihi+1:] = vp[self.ihi]

    def scratch_array(self):
        return np.zeros((2*self.ng+self.nx), dtype=np.float64)

    def initialize(self):
        """ initial conditions """

        phi = self.data["phi"]
        phi[:] = 0.0
        phi[self.nx/2-0.15*self.nx:self.nx/2+0.15*self.nx+1] = 1.0


def evolve(nx, kappa, tau, tmax):
    """
    the main evolution loop.  Evolve

     phi_t = kappa phi_{xx} + (1/tau) R(phi)

    from t = 0 to tmax
    """

    # create the grid
    gr = Grid(nx, ng=1, xmin = 0.0, xmax=50.0,
              vars=["phi", "phi1", "phi2"])

    # pointers to the data at various stages
    phi  = gr.data["phi"]
    phi1 = gr.data["phi1"]
    phi2 = gr.data["phi2"]

    # initialize
    gr.initialize()

    # runtime plotting
    plt.ion()

    t = 0.0
    while t < tmax:

        dt = est_dt(gr, kappa, tau)

        if t + dt > tmax:
            dt = tmax - t

        # react for dt/2
        phi1[:] = react(gr, phi, tau, dt/2)
        gr.fillBC("phi1")

        # diffuse for dt
        phi2[:] = diffuse(gr, phi1, kappa, dt)
        gr.fillBC("phi2")

        # react for dt/2 -- this is the updated solution
        phi[:] = react(gr, phi2, tau, dt/2)
        gr.fillBC("phi")

        t += dt

        plt.clf()
        plt.plot(gr.x, phi)
        plt.xlim(gr.xmin,gr.xmax)
        plt.ylim(0.0,1.0)
        plt.draw()

    return phi, gr.x


# phi is a reaction progress variable, so phi lies between 0 and 1

kappa = 0.1
tau = 1.0

tmax1 = 25.0

nx = 512

phi1, x1 = evolve(nx, kappa, tau, tmax1)

tmax2 = 40.0

phi2, x2 = evolve(nx, kappa, tau, tmax2)

plt.plot(x1, phi1)
plt.plot(x2, phi2, ls=":")
plt.savefig("flame.png")


# estimate the speed -- interpolate to x corresponding to where phi > 0.5
idx = (np.where(phi1 >= 0.5))[0][0]
print("index = ", idx)
xa = x1[idx-1]
xb = x1[idx+1]
phia = phi1[idx-1]
phib = phi1[idx+1]
xpos1 = ((xa - xb)/(phia - phib))*(phia - 0.5) + xa

idx = (np.where(phi2 >= 0.5))[0][0]
xa = x2[idx-1]
xb = x2[idx+1]
phia = phi2[idx-1]
phib = phi2[idx+1]
xpos2 = ((xa - xb)/(phia - phib))*(phia - 0.5) + xa

print(xpos1, xpos2)
print( (xpos1 - xpos2)/(tmax1 - tmax2), np.sqrt(kappa/tau))
