import sys
import numpy
from matplotlib import pyplot
import weno_coefficients
import riemann

class Grid1d(object):

    def __init__(self, nx, ng, xmin=0.0, xmax=1.0, bc="outflow"):

        self.ng = ng
        self.nx = nx

        self.xmin = xmin
        self.xmax = xmax
        
        self.bc = bc

        # python is zero-based.  Make easy intergers to know where the
        # real data lives
        self.ilo = ng
        self.ihi = ng+nx-1

        # physical coords -- cell-centered, left and right edges
        self.dx = (xmax - xmin)/(nx)
        self.x = xmin + (numpy.arange(nx+2*ng)-ng+0.5)*self.dx

        # storage for the solution
        self.q = numpy.zeros((3,(nx+2*ng)), dtype=numpy.float64)


    def scratch_array(self):
        """ return a scratch array dimensioned for our grid """
        return numpy.zeros((3, (self.nx+2*self.ng)), dtype=numpy.float64)


    def fill_BCs(self):
        """ fill all ghostcells as periodic """

        if self.bc == "periodic":

            # left boundary
            self.q[:, 0:self.ilo] = self.q[:, self.ihi-self.ng+1:self.ihi+1]

            # right boundary
            self.q[:, self.ihi+1:] = self.q[:, self.ilo:self.ilo+self.ng]

        elif self.bc == "outflow":

            for n in range(self.ng):
                # left boundary
                self.q[:, n] = self.q[:, self.ilo]
    
                # right boundary
                self.q[:, self.ihi+1+n] = self.q[:, self.ihi]

        else:
            sys.exit("invalid BC")


def weno(order, q):
    """
    Do WENO reconstruction
    
    Parameters
    ----------
    
    order : int
        The stencil width
    q : numpy array
        Scalar data to reconstruct
        
    Returns
    -------
    
    qL : numpy array
        Reconstructed data - boundary points are zero
    """
    C = weno_coefficients.C_all[order]
    a = weno_coefficients.a_all[order]
    sigma = weno_coefficients.sigma_all[order]

    qL = numpy.zeros_like(q)
    beta = numpy.zeros((order, q.shape[1]))
    w = numpy.zeros_like(beta)
    np = q.shape[1] - 2 * order
    epsilon = 1e-16
    for nv in range(3):
        for i in range(order, np+order):
            q_stencils = numpy.zeros(order)
            alpha = numpy.zeros(order)
            for k in range(order):
                for l in range(order):
                    for m in range(l+1):
                        beta[k, i] += sigma[k, l, m] * q[nv, i+k-l] * q[nv, i+k-m]
                alpha[k] = C[k] / (epsilon + beta[k, i]**2)
                for l in range(order):
                    q_stencils[k] += a[k, l] * q[nv, i+k-l]
            w[:, i] = alpha / numpy.sum(alpha)
            qL[nv, i] = numpy.dot(w[:, i], q_stencils)
    
    return qL


class WENOSimulation(object):
    
    def __init__(self, grid, C=0.5, weno_order=3, eos_gamma=1.4):
        self.grid = grid
        self.t = 0.0 # simulation time
        self.C = C   # CFL number
        self.weno_order = weno_order
        self.eos_gamma = eos_gamma # Gamma law EOS

    def init_cond(self, type="sod"):
        if type == "sod":
            rho_l = 1
            rho_r = 1 / 8
            v_l = 0
            v_r = 0
            p_l = 1
            p_r = 1 / 10
            S_l = rho_l * v_l
            S_r = rho_r * v_r
            e_l = p_l / rho_l / (self.eos_gamma - 1)
            e_r = p_r / rho_r / (self.eos_gamma - 1)
            E_l = rho_l * (e_l + v_l**2 / 2)
            E_r = rho_r * (e_r + v_r**2 / 2)
            self.grid.q[0] = numpy.where(self.grid.x < 0,
                                         rho_l * numpy.ones_like(self.grid.x),
                                         rho_r * numpy.ones_like(self.grid.x))
            self.grid.q[1] = numpy.where(self.grid.x < 0,
                                         S_l * numpy.ones_like(self.grid.x),
                                         S_r * numpy.ones_like(self.grid.x))
            self.grid.q[2] = numpy.where(self.grid.x < 0,
                                         E_l * numpy.ones_like(self.grid.x),
                                         E_r * numpy.ones_like(self.grid.x))
        elif type == "advection":
            x = self.grid.x
            rho_0 = 1e-2 # Note: cheated to avoid vacuum
            rho_1 = 1
            sigma = 0.1
            rho = rho_0 * numpy.ones_like(x)
            rho += (rho_1 - rho_0) * numpy.exp(-(x-0.5)**2/sigma**2)
            v = numpy.ones_like(x)
            p = 1e-6 * numpy.ones_like(x)
            S = rho * v
            e = p / rho / (self.eos_gamma - 1)
            E = rho * (e + v**2 / 2)
            self.grid.q[0, :] = rho[:]
            self.grid.q[1, :] = S[:]
            self.grid.q[2, :] = E[:]

    def timestep(self):
        rho = self.grid.q[0]
        v = self.grid.q[1] / rho
        p = (self.eos_gamma - 1) * (self.grid.q[2, :] - rho * v**2 / 2)
        cs = numpy.sqrt(self.eos_gamma * p / rho)
        max_lambda = max(numpy.abs(v) + cs)
        return self.C * self.grid.dx / max_lambda

    def euler_flux(self, q):
        flux = numpy.zeros_like(q)
        rho = q[0, :]
        S = q[1, :]
        E = q[2, :]
        v = S / rho
        p = (self.eos_gamma - 1) * (E - rho * v**2 / 2)
        flux[0, :] = S
        flux[1, :] = S * v + p
        flux[2, :] = (E + p) * v
        return flux


    def rk_substep(self):
        
        g = self.grid
        g.fill_BCs()
        f = self.euler_flux(g.q)
        alpha = numpy.max(abs(g.q))
        fp = (f + alpha * g.q) / 2
        fm = (f - alpha * g.q) / 2
        fpr = g.scratch_array()
        fml = g.scratch_array()
        flux = g.scratch_array()
        fpr[:, 1:] = weno(self.weno_order, fp[:, :-1])
        fml[:, -1::-1] = weno(self.weno_order, fm[:, -1::-1])
        flux[:, 1:-1] = fpr[:, 1:-1] + fml[:, 1:-1]
        rhs = g.scratch_array()
        rhs[:, 1:-1] = 1/g.dx * (flux[:, 1:-1] - flux[:, 2:])
        return rhs


    def evolve(self, tmax):
        """ evolve the Euler equation using RK4 """
        self.t = 0.0
        g = self.grid

        # main evolution loop
        while self.t < tmax:

            # fill the boundary conditions
            g.fill_BCs()

            # get the timestep
            dt = self.timestep()

            if self.t + dt > tmax:
                dt = tmax - self.t

            # RK4
            # Store the data at the start of the step
            q_start = g.q.copy()
            k1 = dt * self.rk_substep()
            g.q = q_start + k1 / 2
            k2 = dt * self.rk_substep()
            g.q = q_start + k2 / 2
            k3 = dt * self.rk_substep()
            g.q = q_start + k3
            k4 = dt * self.rk_substep()
            g.q = q_start + (k1 + 2 * (k2 + k3) + k4) / 6

            self.t += dt
#            print("t=", self.t)



if __name__ == "__main__":

    
    # setup the problem -- Sod
    left = riemann.State(p=1.0, u=0.0, rho=1.0)
    right = riemann.State(p=0.1, u=0.0, rho=0.125)

    rp = riemann.RiemannProblem(left, right)
    rp.find_star_state()

    x_e, rho_e, v_e, p_e = rp.sample_solution(0.2, 1024)
    e_e = p_e / 0.4 / rho_e
    
    #-----------------------------------------------------------------------------
    # Sod
    
    xmin = -0.5
    xmax = 0.5
    nx = 64
    
    tmax = 0.2
    C = 0.5
    
    for order in range(3, 7):
    
        ng = order+1
        g = Grid1d(nx, ng, xmin, xmax, bc="outflow")
        
        pyplot.clf()
        
        s = WENOSimulation(g, C, order)
        s.init_cond("sod")
        s.evolve(tmax)
        g = s.grid
        x = g.x + 0.5
        rho = g.q[0, :]
        v = g.q[1, :] / g.q[0, :]
        e = (g.q[2, :] - rho * v**2 / 2) / rho
        p = (s.eos_gamma - 1) * (g.q[2, :] - rho * v**2 / 2)
        fig, axes = pyplot.subplots(4, 1, sharex=True, figsize=(6,10))
        axes[0].plot(x[g.ilo:g.ihi+1], rho[g.ilo:g.ihi+1], 'bo')
        axes[0].plot(x_e, rho_e, 'k--')
        axes[0].set_ylabel(r"$\rho$")
        axes[1].plot(x[g.ilo:g.ihi+1], v[g.ilo:g.ihi+1], 'bo')
        axes[1].plot(x_e, v_e, 'k--')
        axes[1].set_ylabel(r"$u$")
        axes[2].plot(x[g.ilo:g.ihi+1], p[g.ilo:g.ihi+1], 'bo')
        axes[2].plot(x_e, p_e, 'k--')
        axes[2].set_xlabel(r"$x$")
        axes[3].plot(x[g.ilo:g.ihi+1], e[g.ilo:g.ihi+1], 'bo')
        axes[3].plot(x_e, e_e, 'k--')
        axes[3].set_xlabel(r"$x$")
        axes[3].set_ylabel(r"$e$")
        for ax in axes:
            ax.set_xlim(0, 1)
        axes[0].set_title(r"Sod test, WENO, $r={}$".format(order))
        fig.tight_layout()
        pyplot.show()


    # Advection
    # There seems to be an odd instability kicking in after t=1
    # Vacuum formation?
    # Changing the lower threshold has no impact
    # But it warns about invalid sqrt in the speed of sound, so
    # negative density. Odd.
    # Might want to check BCs.
    
    xmin = 0
    xmax = 1
    nx = 128
    
    tmax = 1
    C = 0.5
    
    order = 3
    ng = order+1
    g = Grid1d(nx, ng, xmin, xmax, bc="periodic")
    
    pyplot.clf()
    
    s = WENOSimulation(g, C, order)
    s.init_cond("advection")
    rho_0 = s.grid.q[0, :].copy()
    s.evolve(tmax)
    g = s.grid
    rho = g.q[0, :]
    v = g.q[1, :] / g.q[0, :]
    e = (g.q[2, :] - rho * v**2 / 2) / rho
    p = (s.eos_gamma - 1) * (g.q[2, :] - rho * v**2 / 2)
    pyplot.plot(g.x[g.ilo:g.ihi+1], rho[g.ilo:g.ihi+1], 'bo',
                label=r"WENO, r={}".format(order))
    pyplot.plot(g.x[g.ilo:g.ihi+1], rho_0[g.ilo:g.ihi+1], 'k-',
                label="Exact")
    pyplot.legend()
    pyplot.xlabel(r"$x$")
    pyplot.ylabel(r"$\rho$")
    pyplot.xlim(0, 1)
    pyplot.show()
    