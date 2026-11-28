# Results and limitations

Two independent separations emerge. First, enrichment and split-transcript repair are producer operations, while the validator reads the existing journal tree, index and manifest. This makes a clean validation run a different observation from successfully re-running every producer. Second, local machine artifacts such as media and credential caches have a restricted retention boundary, whereas curated descriptions, transcript data, captions and translations have their own public corpus policy.

The validator's documented scope includes duplicate targets, canonical identity, manifest coverage and restrictions on credentials and audio. These checks can find inconsistencies in a snapshot. They do not estimate word error rates, assess diarisation fairness or demonstrate successful platform publication. GPU transcription, hosted translation and OAuth-backed writes have explicit dependencies outside the inspected source tree.
