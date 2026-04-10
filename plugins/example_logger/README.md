# Example Logger Plugin

A reference plugin that demonstrates the DupeZ plugin API. Logs disruption lifecycle events to an in-memory store.

## Creating a DupeZ Plugin

### Folder Structure

```
plugins/
  your_plugin/
    manifest.json    # Required — plugin metadata
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

1. Place your plugin folder in `plugins/`
2. Run DupeZ — check the log output for "Plugin loaded: Your Plugin Name"
3. If activation fails, check `dupez.log` for error details

```python
# Quick test without running DupeZ:
from plugins.example_logger.plugin import ExampleLoggerPlugin

plugin = ExampleLoggerPlugin()
plugin.activate(controller=None)  # None OK for basic testing
plugin.log_event("test", {"message": "hello"})
print(plugin.get_summary())
plugin.deactivate()
```
