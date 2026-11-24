"""Shallow boosted-tree candidate scorer (XGBoost) with an explicit custom pairwise objective.

The objective is the SAME weighted pairwise logistic loss as the linear ranker, on per-candidate
margins s (output_margin):
  p = sigmoid(s_w - s_b);  g_b -= w*p;  g_w += w*p
  h_b += 2*w*p*(1-p);       h_w += 2*w*p*(1-p)
The exact Hessian H = sum w p(1-p) (e_b - e_w)(e_b - e_w)^T is not diagonal; D = diag(h) satisfies
D - H = sum w p(1-p) (e_b + e_w)(e_b + e_w)^T >= 0, i.e. D is a valid diagonal upper bound
(majorizer) used by XGBoost's diagonal second-order interface.

Common scaling: both g and h are multiplied by C = number of retained training pairs (weights sum to
1, so C*w has mean 1 per pair). This is equivalent to the unscaled objective with
reg_lambda/C and min_child_weight/C; the definition of C is identical for every fit.
Rows passed to XGBoost: candidates of training states that occur in >=1 retained pair.
"""
import numpy as np
import xgboost as xgb
from scipy.special import expit

FROZEN_PARAMS = dict(eta=0.05, subsample=1.0, colsample_bytree=1.0, colsample_bylevel=1.0, colsample_bynode=1.0,
                     min_child_weight=1.0, reg_lambda=1.0, reg_alpha=0.0, gamma=0.0, max_delta_step=0.0,
                     tree_method='exact', nthread=1, seed=20261124, base_score=0.0, disable_default_eval_metric=1,
                     validate_parameters=True)


def pair_grad_hess(s, b, w, wt, scale):
    d = s[b] - s[w]; p = expit(-d); q = wt * p; hq = 2.0 * wt * p * (1.0 - p)
    n = len(s)
    g = np.bincount(w, q, minlength=n) - np.bincount(b, q, minlength=n)
    h = np.bincount(b, hq, minlength=n) + np.bincount(w, hq, minlength=n)
    return scale * g, scale * h


def pair_loss(s, b, w, wt):
    return float(np.sum(wt * np.logaddexp(0.0, -(s[b] - s[w]))))


def fit(X, b, w, wt, max_depth, rounds, record_every=10):
    X = np.asarray(X, dtype=np.float64); scale = float(len(b)); trace = []
    d = xgb.DMatrix(X)
    def obj(predt, dmat):
        return pair_grad_hess(predt, b, w, wt, scale)
    params = dict(FROZEN_PARAMS, max_depth=int(max_depth))
    booster = xgb.train(params, d, num_boost_round=int(rounds), obj=obj)
    margin = booster.predict(d, output_margin=True)
    return booster, dict(scale_C=scale, params=params, rounds=int(rounds), train_loss=pair_loss(margin, b, w, wt),
                         finite=bool(np.all(np.isfinite(margin))), xgboost_version=xgb.__version__)


def score(booster, X):
    return booster.predict(xgb.DMatrix(np.asarray(X, dtype=np.float64)), output_margin=True).astype(np.float64)


def load(path):
    bst = xgb.Booster(); bst.load_model(str(path)); return bst
