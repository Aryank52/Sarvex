"""SARVEX-HFCE: Hybrid Frequency-Context Change Ensemble.

A first-party machine-learning algorithm for surface-change classification.
Combines a deterministic scientific baseline with an XGBoost classifier and an
evidence-fusion step. Weights are configurable; nothing is hard-coded forever.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

HFCE_VERSION = "1.0"
EVENT_TYPES = [
    "NO_SIGNIFICANT_CHANGE",
    "SURFACE_DISTURBANCE",
    "GROUND_DEFORMATION",
    "FLOOD_WATER_CHANGE",
    "AGRICULTURAL_CHANGE",
    "VEGETATION_CHANGE",
    "CRYOSPHERE_CHANGE",
    "STRUCTURAL_CHANGE",
    "OTHER_UNKNOWN",
]


@dataclass
class HFCEConfig:
    weights: dict[str, float] = field(default_factory=lambda: {
        "scientific": 0.30,
        "ml": 0.35,
        "temporal": 0.15,
        "spatial": 0.10,
        "context": 0.10,
    })
    xgb_params: dict[str, Any] = field(default_factory=lambda: {
        "n_estimators": 200,
        "max_depth": 4,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "objective": "multi:softprob",
        "eval_metric": "mlogloss",
        "random_state": 42,
        "n_jobs": 2,
    })
    anomaly_threshold: float = 0.5
    min_samples_per_class: int = 5

    def normalized_weights(self) -> dict[str, float]:
        total = sum(self.weights.values()) or 1.0
        return {k: v / total for k, v in self.weights.items()}


@dataclass
class HFCEPrediction:
    event_type: str
    probabilities: dict[str, float]
    change_probability: float
    confidence: float
    uncertainty: float
    top_features: list[dict[str, Any]]
    baseline_score: float
    ml_score: float
    anomaly_score: float
    fusion: dict[str, float]
    model_version: str
    feature_version: str


class SarvexHFCE:
    def __init__(self, config: HFCEConfig | None = None, feature_names: list[str] | None = None) -> None:
        self.config = config or HFCEConfig()
        self.feature_names: list[str] = list(feature_names or [])
        self.model = None
        self.label_encoder: dict[str, int] = {name: i for i, name in enumerate(EVENT_TYPES)}
        self.reverse_encoder: dict[int, str] = {i: name for i, name in enumerate(EVENT_TYPES)}
        self.feature_importance_: dict[str, float] = {}
        self.classes_: list[int] = []
        self.trained = False
        self.training_metadata: dict[str, Any] = {}

    def _to_array(self, X: Any) -> np.ndarray:
        if isinstance(X, dict):
            if not self.feature_names:
                self.feature_names = list(X.keys())
            row = [float(X.get(n, 0.0) or 0.0) if _is_number(X.get(n)) else 0.0 for n in self.feature_names]
            return np.asarray(row, dtype="float64").reshape(1, -1)
        arr = np.asarray(X, dtype="float64")
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr

    def _clean(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype="float64").copy()
        X[~np.isfinite(X)] = 0.0
        return X

    def deterministic_baseline_score(self, features: dict[str, Any]) -> float:
        """Transparent scientific score in [0,1]."""
        score = 0.0
        # backscatter change magnitude
        bc = features.get("backscatter_change_median_db")
        if bc is not None:
            score += min(abs(float(bc)) / 5.0, 1.0) * 0.25
        # displacement magnitude
        dm = features.get("displacement_median_mm")
        if dm is not None:
            score += min(abs(float(dm)) / 50.0, 1.0) * 0.25
        # coherence drop proxy
        coh = features.get("coherence_mean")
        if coh is not None:
            score += (1.0 - min(max(float(coh), 0.0), 1.0)) * 0.15
        # temporal persistence
        tp = features.get("temporal_sign_changes")
        if tp is not None:
            score += min(float(tp) / 5.0, 1.0) * 0.10
        # spatial extent
        ca = features.get("changed_fraction")
        if ca is not None:
            score += min(float(ca) / 0.2, 1.0) * 0.15
        # polarimetric ratio change
        pr = features.get("vv_vh_ratio_mean_db")  # not change; use ratio std as proxy
        prs = features.get("vv_vh_ratio_std_db")
        if prs is not None:
            score += min(float(prs) / 3.0, 1.0) * 0.10
        return float(min(max(score, 0.0), 1.0))

    def anomaly_score(self, features: dict[str, Any]) -> float:
        # simple anomaly: how many features exceed robust thresholds
        vals = [v for v in features.values() if _is_number(v)]
        if not vals:
            return 0.0
        arr = np.asarray(vals, dtype="float64")
        med = np.median(arr)
        mad = np.median(np.abs(arr - med)) or 1e-6
        z = np.abs((arr - med) / (1.4826 * mad + 1e-9))
        return float(min(np.mean(z > 3.0), 1.0))

    def fit(self, X: Any, y: Any, feature_names: list[str] | None = None) -> "SarvexHFCE":
        if feature_names:
            self.feature_names = list(feature_names)
        Xa = self._clean(self._to_array(X) if not isinstance(X, (list, tuple, np.ndarray)) else np.asarray(X, dtype="float64"))
        # ensure 2D
        if Xa.ndim == 1:
            Xa = Xa.reshape(1, -1)
        if not self.feature_names:
            self.feature_names = [f"f{i}" for i in range(Xa.shape[1])]
        ya = np.asarray(y)
        # Normalise labels: accept either event-type names or integer class indices.
        if ya.dtype.kind in ("U", "S", "O"):
            y_idx = np.array([self.label_encoder.get(str(v), len(EVENT_TYPES) - 1) for v in ya], dtype=int)
        else:
            y_idx = ya.astype(int)
            # clamp to valid range
            y_idx = np.clip(y_idx, 0, len(EVENT_TYPES) - 1)
        self.classes_ = sorted(set(int(v) for v in y_idx.tolist()))
        # check classes
        classes, counts = np.unique(y_idx, return_counts=True)
        # train XGBoost
        try:
            from xgboost import XGBClassifier
            params = dict(self.config.xgb_params)
            model = XGBClassifier(**params)
        except Exception:  # noqa: BLE001
            from sklearn.ensemble import GradientBoostingClassifier
            model = GradientBoostingClassifier(random_state=42)
        try:
            model.fit(Xa, y_idx)
        except Exception:  # noqa: BLE001
            # fallback: try sklearn random forest
            from sklearn.ensemble import RandomForestClassifier
            model = RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=2)
            model.fit(Xa, y_idx)
        self.model = model
        self.trained = True
        # feature importance
        try:
            imp = getattr(model, "feature_importances_", None)
            if imp is not None:
                self.feature_importance_ = {self.feature_names[i]: float(imp[i]) for i in range(len(self.feature_names))}
        except Exception:  # noqa: BLE001
            self.feature_importance_ = {}
        self.training_metadata = {
            "n_samples": int(Xa.shape[0]),
            "n_features": int(Xa.shape[1]),
            "classes": [self.reverse_encoder.get(int(c), str(c)) for c in classes],
            "class_counts": {self.reverse_encoder.get(int(c), str(c)): int(n) for c, n in zip(classes, counts)},
        }
        return self

    def _ml_probabilities(self, Xa: np.ndarray) -> np.ndarray:
        if self.model is None or not self.trained:
            n = Xa.shape[0]
            return np.full((n, len(EVENT_TYPES)), 1.0 / len(EVENT_TYPES))
        try:
            proba = self.model.predict_proba(Xa)
        except Exception:  # noqa: BLE001
            pred = self.model.predict(Xa)
            proba = np.zeros((Xa.shape[0], len(EVENT_TYPES)))
            for i, p in enumerate(pred):
                ci = int(p)
                if 0 <= ci < len(EVENT_TYPES):
                    proba[i, ci] = 1.0
            return proba
        # align columns to full EVENT_TYPES set using model.classes_
        classes = getattr(self.model, "classes_", None)
        if classes is None:
            classes = getattr(self, "classes_", list(range(proba.shape[1])))
        full = np.zeros((proba.shape[0], len(EVENT_TYPES)))
        for j, c in enumerate(classes):
            ci = int(c)
            if 0 <= ci < len(EVENT_TYPES) and j < proba.shape[1]:
                full[:, ci] = proba[:, j]
        return full

    def predict(self, features: dict[str, Any] | Any, feature_names: list[str] | None = None) -> HFCEPrediction:
        if feature_names and not self.feature_names:
            self.feature_names = list(feature_names)
        if isinstance(features, dict):
            if not self.feature_names:
                self.feature_names = list(features.keys())
            vec = self._to_array(features)
        else:
            vec = self._to_array(features) if not isinstance(features, (list, tuple, np.ndarray)) else np.asarray(features, dtype="float64").reshape(1, -1)
        vec = self._clean(vec)
        # align width
        if self.feature_names and vec.shape[1] != len(self.feature_names):
            # pad/truncate
            new = np.zeros((vec.shape[0], len(self.feature_names)))
            m = min(vec.shape[1], len(self.feature_names))
            new[:, :m] = vec[:, :m]
            vec = new
        proba = self._ml_probabilities(vec)[0]
        ml_top_idx = int(np.argmax(proba))
        ml_event = self.reverse_encoder.get(ml_top_idx, "OTHER_UNKNOWN")
        ml_prob = float(proba[ml_top_idx])
        baseline = self.deterministic_baseline_score(features if isinstance(features, dict) else {})
        anomaly = self.anomaly_score(features if isinstance(features, dict) else {})
        # temporal/spatial/context proxies from features
        temporal = float(min((features.get("temporal_sign_changes", 0) or 0) / 5.0, 1.0)) if isinstance(features, dict) else 0.0
        spatial = float(min((features.get("changed_fraction", 0) or 0) / 0.2, 1.0)) if isinstance(features, dict) else 0.0
        context = float(1.0 if isinstance(features, dict) and features.get("distance_to_water_m") is not None else 0.0) * 0.5
        w = self.config.normalized_weights()
        scientific_score = baseline
        fusion_score = (
            w["scientific"] * scientific_score
            + w["ml"] * ml_prob
            + w["temporal"] * temporal
            + w["spatial"] * spatial
            + w["context"] * context
        )
        # final event type: prefer ML if confident else baseline-driven
        if ml_prob >= 0.5 and self.trained:
            final_event = ml_event
        else:
            # if no significant change
            if baseline < 0.15 and anomaly < 0.2:
                final_event = "NO_SIGNIFICANT_CHANGE"
            else:
                final_event = ml_event if self.trained else "SURFACE_DISTURBANCE"
        # change probability
        change_prob = float(min(max(fusion_score, 0.0), 1.0))
        # uncertainty: 1 - max proba, plus anomaly disagreement
        uncertainty = float(min(max(1.0 - max(proba.max() if proba.size else 0.0, fusion_score), 0.0), 1.0))
        confidence = float(min(max(max(proba.max() if proba.size else 0.0, fusion_score), 0.0), 1.0))
        # top features from importance
        top = sorted(self.feature_importance_.items(), key=lambda kv: kv[1], reverse=True)[:8]
        top_features = [{"feature": k, "importance": v} for k, v in top]
        if not top_features and isinstance(features, dict):
            # fallback: rank by absolute value
            ranked = sorted(features.items(), key=lambda kv: abs(kv[1]) if _is_number(kv[1]) else 0.0, reverse=True)[:8]
            top_features = [{"feature": k, "value": v} for k, v in ranked]
        prob_map = {self.reverse_encoder.get(i, EVENT_TYPES[i] if i < len(EVENT_TYPES) else "OTHER_UNKNOWN"): float(proba[i]) for i in range(len(proba))}
        return HFCEPrediction(
            event_type=final_event,
            probabilities=prob_map,
            change_probability=change_prob,
            confidence=confidence,
            uncertainty=uncertainty,
            top_features=top_features,
            baseline_score=float(baseline),
            ml_score=float(ml_prob),
            anomaly_score=float(anomaly),
            fusion={"scientific": scientific_score, "ml": ml_prob, "temporal": temporal, "spatial": spatial, "context": context, "final": fusion_score},
            model_version=HFCE_VERSION if not self.trained else (self.training_metadata.get("model_version", HFCE_VERSION)),
            feature_version="sar_feature_engine_v1",
        )

    def explain(self) -> dict[str, Any]:
        return {
            "model": "SARVEX-HFCE",
            "version": HFCE_VERSION,
            "trained": self.trained,
            "weights": self.config.normalized_weights(),
            "feature_importance": self.feature_importance_,
            "training_metadata": self.training_metadata,
            "event_types": EVENT_TYPES,
        }

    def save(self, path: str | Path) -> dict[str, str]:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        if self.model is not None:
            try:
                self.model.save_model(str(p / "model.json"))
            except Exception:  # noqa: BLE001
                import pickle
                with open(p / "model.pkl", "wb") as f:
                    pickle.dump(self.model, f)
        (p / "feature_names.json").write_text(json.dumps(self.feature_names))
        (p / "config.json").write_text(json.dumps({"weights": self.config.weights, "xgb_params": self.config.xgb_params}))
        (p / "feature_importance.json").write_text(json.dumps(self.feature_importance_))
        (p / "training_metadata.json").write_text(json.dumps(self.training_metadata))
        (p / "version.txt").write_text(HFCE_VERSION)
        return {"artifact_dir": str(p)}

    @classmethod
    def load(cls, path: str | Path) -> "SarvexHFCE":
        p = Path(path)
        obj = cls()
        obj.feature_names = json.loads((p / "feature_names.json").read_text()) if (p / "feature_names.json").exists() else []
        if (p / "config.json").exists():
            cfg = json.loads((p / "config.json").read_text())
            obj.config.weights = cfg.get("weights", obj.config.weights)
            obj.config.xgb_params = cfg.get("xgb_params", obj.config.xgb_params)
        if (p / "feature_importance.json").exists():
            obj.feature_importance_ = json.loads((p / "feature_importance.json").read_text())
        if (p / "training_metadata.json").exists():
            obj.training_metadata = json.loads((p / "training_metadata.json").read_text())
        # load model
        model_path = p / "model.json"
        if model_path.exists():
            try:
                from xgboost import XGBClassifier
                m = XGBClassifier()
                m.load_model(str(model_path))
                obj.model = m
                obj.trained = True
            except Exception:  # noqa: BLE001
                obj.trained = False
        elif (p / "model.pkl").exists():
            import pickle
            with open(p / "model.pkl", "rb") as f:
                obj.model = pickle.load(f)
            obj.trained = True
        if (p / "version.txt").exists():
            obj.training_metadata.setdefault("model_version", (p / "version.txt").read_text().strip())
        return obj


def _is_number(v: Any) -> bool:
    try:
        return isinstance(v, (int, float, np.integer, np.floating)) and np.isfinite(v)
    except Exception:  # noqa: BLE001
        return False
