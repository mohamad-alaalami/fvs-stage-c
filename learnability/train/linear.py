"""Linear pairwise logistic ranker: s = Phi @ theta.

  L(theta) = sum_pairs w_bw * log(1 + exp(-(s_b - s_w))) + lambda/2 * ||theta||^2
computed with numpy.logaddexp (stable). Gradient: dL/ds_b = -w*p, dL/ds_w = +w*p with
p = sigmoid(s_w - s_b); dL/dtheta = Phi^T (dL/ds) + lambda*theta.
Optimiser: scipy.optimize.minimize(method='L-BFGS-B'), theta0 = 0, with fixed options
(maxiter=10000, maxfun=50000, gtol=1e-8, ftol=1e-14, maxcor=20).
Converged iff the final gradient infinity-norm <= 1e-6, theta is finite, and the iteration limit was
not reached (the optimiser's own message, e.g. a line-search stop at rounding level, is recorded but
does not decide). Anything else is a FAILED fit (never used as a valid model).
"""
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

OPTIONS = dict(maxiter=10000, maxfun=50000, gtol=1e-8, ftol=1e-14, maxcor=20)
GRAD_TOL = 1e-6


def loss_grad(theta, Phi, b, w, wt, lam):
    s = Phi @ theta
    d = s[b] - s[w]
    loss = float(np.sum(wt * np.logaddexp(0.0, -d))) + 0.5 * lam * float(theta @ theta)
    p = expit(-d)                                    # sigmoid(s_w - s_b)
    gs = np.bincount(w, wt * p, minlength=len(s)) - np.bincount(b, wt * p, minlength=len(s))
    return loss, Phi.T @ gs + lam * theta


def fit(Phi, b, w, wt, lam):
    Phi = np.ascontiguousarray(Phi, dtype=np.float64); theta0 = np.zeros(Phi.shape[1])
    res = minimize(loss_grad, theta0, args=(Phi, b, w, wt, lam), jac=True, method='L-BFGS-B', options=OPTIONS)
    _, g = loss_grad(res.x, Phi, b, w, wt, lam)
    gnorm = float(np.max(np.abs(g))) if g.size else 0.0
    converged = gnorm <= GRAD_TOL and bool(np.all(np.isfinite(res.x))) and int(res.nit) < OPTIONS['maxiter']
    return res.x, dict(converged=converged, optimizer_success=bool(res.success), message=str(res.message), iterations=int(res.nit),
                       function_evaluations=int(res.nfev), final_objective=float(res.fun), grad_inf_norm=gnorm,
                       options=OPTIONS, grad_tol=GRAD_TOL)


def score(theta, Phi):
    return np.asarray(Phi, dtype=np.float64) @ theta
