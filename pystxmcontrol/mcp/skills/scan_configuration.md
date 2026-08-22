---
name: scan-configuration
description: Comprehensive scan configuration checklist
---

# Scan Configuration Checklist

When configuring scans from a user prompt, follow these steps:

## Update the scan configuration
- [ ] Run get_config(), this returns the configuration of recently run scans, available scan types, available motors and detectors.  This is important because other remote processes may run scans
- [ ] Ask the user the scan type if they did not indicate it in their prompt.  Prompt the user with the available options.
- [ ] run update_scan() to update the config with the requested scan type and any other arguments the user supplies
- [ ] present the updated configuration to the user for confirmation

## Run the scan and visualize
- [ ] Once the user confirms the configuration above, execute stxm_scan()
- [ ] When the scan returns, load the file and display the first frame

## Wrap up
- [ ] After the scan data is display, ask the user what they wish to do next
- [ ] Do not provide commentary on the recent process or the data acquired
- [ ] Do not make recommendations for further data acquisition unless prompted by the user