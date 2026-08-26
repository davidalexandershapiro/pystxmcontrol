---
name: scan-configuration
description: Comprehensive scan configuration checklist
---

# Scan Configuration Checklist

When configuring scans from a user prompt, follow these steps:

## Update the scan configuration
- [ ] Run get_config(), which by default returns a compact summary: available scan types, a motor summary (units/limits), current positions, and DAQ names.  This is important because other remote processes may run scans.
- [ ] Ask the user the scan type if they did not indicate it in their prompt.  Prompt the user with the available scan types from the summary.
- [ ] Call get_config(section="lastScan") to retrieve the last-used parameters (keyed by scan type); read the entry for the chosen scan type and use it as the basis for update_scan.  Use get_config(section="motors") or "daqs" only if you need full motor/detector detail.
- [ ] If the user names an absorption edge or a standard scan ("C 1s stack", "the Fe L3 preset") rather than giving explicit energies, call list_energy_presets() and apply the matching one with update_scan(energy_preset="<name>").  These are the energy definitions the operator saved in the GUI; applying one by name saves the user typing out every energy region, and preserves each region's own dwell.  If no preset matches, ask for the energy ranges instead of guessing.
- [ ] run update_scan() to update the config with the requested scan type and any other arguments the user supplies
- [ ] present the updated configuration to the user for confirmation.  When a preset was applied, show its energy regions (start/stop/points/dwell each) so the user can see what will be measured.

## Run the scan and visualize
- [ ] Once the user confirms the configuration above, execute stxm_scan()
- [ ] When the scan returns, load the file and display the first frame

## Wrap up
- [ ] After the scan data is display, ask the user what they wish to do next
- [ ] Do not provide commentary on the recent process or the data acquired
- [ ] Do not make recommendations for further data acquisition unless prompted by the user