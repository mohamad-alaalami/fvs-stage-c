"""Feature roles and the linear model's training-only transformation.

Model inputs are exactly the extraction schema allowlists. Candidate-specific vs shared-state split:
candidate columns describe v (f_cand_*, f_nbr_*, f_lp_root_common_neighbors); context columns are
the state-level f_state_* values repeated on every candidate row.

Linear features phi(v), in order:
  z_c = (x_c - mean_c) / std_c for each candidate column c       (std: population, ddof=0)
  y_ck = z_c * z_k for each candidate c and context k (context z_k likewise standardised),
         then standardised again: (y_ck - mean_ck) / std_ck
Zero-variance columns map to 0. Means/stds come only from the training rows given to fit().
Pure context terms are omitted (they cancel in pairwise score differences); no intercept.
"""
import numpy as np

from learnability.schema import ALLOWLISTS

CANDIDATE_PREFIXES = ('f_cand_', 'f_nbr_', 'f_lp_')
ABLATION_REMOVED = ('f_nbr_none_wdeg_min', 'f_nbr_none_wdeg_mean', 'f_nbr_none_wdeg_max', 'f_lp_root_common_neighbors')


def inputs_for(solver, ablation=False):
    cols = list(ALLOWLISTS[solver])
    return [c for c in cols if c not in ABLATION_REMOVED] if ablation else cols


def split(columns):
    cand = [c for c in columns if c.startswith(CANDIDATE_PREFIXES)]
    ctx = [c for c in columns if c.startswith('f_state_')]
    assert sorted(cand + ctx) == sorted(columns), columns
    return cand, ctx


def _stats(X):
    mean = X.mean(axis=0); std = X.std(axis=0)  # population std
    return mean, std


def _apply(X, mean, std):
    out = np.zeros_like(X)
    nz = std > 0
    out[:, nz] = (X[:, nz] - mean[nz]) / std[nz]
    return out


class LinearTransform:
    def __init__(self, columns):
        self.columns = list(columns); self.cand, self.ctx = split(self.columns)
        self.ci = [self.columns.index(c) for c in self.cand]; self.ki = [self.columns.index(c) for c in self.ctx]

    def fit(self, X):
        X = np.asarray(X, dtype=np.float64)
        self.base_mean, self.base_std = _stats(X)
        Z = _apply(X, self.base_mean, self.base_std)
        P = self._products(Z)
        self.prod_mean, self.prod_std = _stats(P)
        return self

    def _products(self, Z):
        return np.stack([Z[:, c] * Z[:, k] for c in self.ci for k in self.ki], axis=1) if self.ki else np.zeros((len(Z), 0))

    def transform(self, X):
        X = np.asarray(X, dtype=np.float64)
        Z = _apply(X, self.base_mean, self.base_std)
        return np.concatenate([Z[:, self.ci], _apply(self._products(Z), self.prod_mean, self.prod_std)], axis=1)

    def names(self):
        return list(self.cand) + [f'{c}*{k}' for c in self.cand for k in self.ctx]

    def export(self):
        return dict(input_order=self.columns, candidate_columns=self.cand, context_columns=self.ctx,
                    base=[dict(column=c, mean=float(m), std=float(s)) for c, m, s in zip(self.columns, self.base_mean, self.base_std)],
                    products=[dict(candidate=c, context=k, mean=float(m), std=float(s)) for (c, k), m, s in
                              zip([(c, k) for c in self.cand for k in self.ctx], self.prod_mean, self.prod_std)],
                    phi_order=self.names(), zero_variance_rule='a column with std == 0 maps to 0')

    @classmethod
    def from_export(cls, d):
        t = cls(d['input_order'])
        t.base_mean = np.array([b['mean'] for b in d['base']]); t.base_std = np.array([b['std'] for b in d['base']])
        t.prod_mean = np.array([p['mean'] for p in d['products']]); t.prod_std = np.array([p['std'] for p in d['products']])
        return t
