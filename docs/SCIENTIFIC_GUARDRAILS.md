# Scientific guardrails

1. **No invented science.** The language model explains supplied measurements;
   it cannot add a measurement, change a unit or confirm an event.
2. **Units everywhere.** Every statistic carries units; reports and API keep
   them.
3. **Uncertainty is first-class.** Displacement, detection and answer confidence
   are separate quantities. None is a hazard probability.
4. **Provenance is immutable.** Algorithm, version, parameters, inputs, CRS,
   units, timestamps and code version are stored with the run.
5. **Demo is explicit.** Synthetic fixtures are labelled at every level and
   never presented as NASA/ISRO data.
6. **Models are configuration.** No model name is hard-coded in business logic.
7. **No silent truncation.** Vectors above capacity are rejected; shorter
   vectors are zero-padded.
8. **Confirmation gate.** Demo events cannot be confirmed; synthetic evidence is
   rejected; a URL or citation is mandatory.
9. **Evidence stages.** OBSERVED, DERIVED, DETECTED, CLASSIFIED, HYPOTHESIZED,
   CONTEXTUALIZED, CONFIRMED. A detection is never automatically promoted.
10. **Spatial proximity is not causality.** Exposure and context are labelled as
    such.
