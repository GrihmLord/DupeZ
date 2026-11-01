# Example Logger Plugin

A reference plugin that demonstrates the DupeZ plugin API. Logs disruption lifecycle events to an in-memory store.

## Creating a DupeZ Plugin

### Folder Structure

```
plugins/
  your_plugin/
    manifest.json    # Required — plugin metadata
    manifest.json.sig # Required for trusted production loading
    plugin.py        # Required — entry point module
    README.md        # Recommended
```

### manifest.json

```json
{
    "name": "Your Plugin Name",
    "version": "1.0.0",
    "description": "What your plugin does",
    "type": "generic",
    "entry_point": "plugin.py",
    "author": "Your Name",
    "min_dupez_version": "4.0.0"
}
```

**Plugin types:** `generic`, `disruption`, `scanner`, `ui_panel`

### Plugin Types

| Type | Base Class | Use Case |
|------|-----------|----------|
| `generic` | `GenericPlugin` | Background logic, logging, webhooks, integrations |
| `disruption` | `DisruptionPlugin` | New packet manipulation methods |
| `scanner` | `ScannerPlugin` | New network scanning capabilities |
| `ui_panel` | `UIPanelPlugin` | New sidebar views in the dashboard |

### Signing and Activation

Before distribution, remove `__pycache__` directories and sign the complete
plugin folder with `python scripts/sign-plugin.py --sign --priv <key> --plugin-dir
<folder>`. The tool upgrades the metadata to manifest v2 and authenticates the
canonical path, size, and SHA-384 of every Python helper, native module, README,
and resource. Adding, removing, or editing any inventoried file invalidates the
bundle. Entry-only manifests from older tools must be re-signed.

Production loading also requires the publisher public key to be pinned in a
DupeZ release. For local development only, set `DUPEZ_PLUGIN_DEV_MODE=1`; the UI
and audit log identify the plugin as `DEV_UNSIGNED`, never trusted.

Keep `dependencies` empty: third-party plugin dependencies are rejected until
DupeZ can authenticate their installed distribution version and every executed
file. The loader preloads its documented standard-library and host API surface
to make ordinary imports deterministic, but the publisher remains fully trusted
for all code in the signed bundle. Python capability checks are diagnostic,
not an isolation boundary.

### Activation Lifecycle

1. DupeZ starts and `PluginLoader.discover()` scans `plugins/` for `manifest.json` files
2. Each manifest is validated (required fields, valid type, version compatibility)
3. `PluginLoader.load_all(controller)` imports each `entry_point` module
4. The loader instantiates the plugin class and calls `activate(controller)`
5. On shutdown, `deactivate()` is called for cleanup

### The Controller

Your plugin receives the `AppController` on activation. Through it you can:

- `controller.get_devices()` — list scanned network devices
- `controller.get_disrupted_devices()` — list of IPs under active disruption
- `controller.disrupt_device(ip, methods, params)` — start disruption
- `controller.stop_disruption(ip)` — stop disruption
- `controller.state` — access app settings and state

### Testing Locally

1. Create a local signing key and sign the folder so it has a complete v2 inventory.
2. Set `DUPEZ_PLUGIN_DEV_MODE=1` and place the folder in `plugins/`.
3. Run DupeZ and confirm the log identifies it as `DEV_UNSIGNED`.
4. If activation fails, check `dupez.log` for integrity or capability errors.

```python
# Basic unit test without the loader (this does not verify bundle integrity):
from plugins.example_logger.plugin import ExampleLoggerPlugin

plugin = ExampleLoggerPlugin()
plugin.activate(controller=None)  # None OK for basic testing
plugin.log_event("test", {"message": "hello"})
print(plugin.get_summary())
plugin.deactivate()
```
