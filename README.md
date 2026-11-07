# KAC Home Assistant Add-on

This repository contains an installable Home Assistant add-on that reads arbitrary Home Assistant entities and sends documented page/row data to devices running the **KleinerAnzeigeComputer (KAC)** firmware.

[![Open your Home Assistant instance and add this repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fhighno%2Fkac-home-assistant-addon)

The implementation follows the public KAC API and does not guess undocumented fields. See [`kac_display/DOCS.md`](kac_display/DOCS.md) for installation, configuration, verified limits, and open points.

## Repository layout

```text
kac_display/            Home Assistant add-on
  app/                  Python application
  examples/kac.yaml     complete example configuration
  tests/                offline unit tests
repository.yaml         repository metadata for Home Assistant
```

Repository URL: <https://github.com/highno/kac-home-assistant-addon>

