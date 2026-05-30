# diffstream

Pure protocol primitives for GripLab synthetic diff streams.

This package owns the structured diff payload model and JSON codec for
`application/vnd.griplab.diff+json;version=1`. It intentionally has no imports
from `griplab_service`, websocket code, watchdog, git integrations, or GRIP.
