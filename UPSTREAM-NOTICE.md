# Upstream notice

This automation targets:

- Project: MoonTVPlus
- Upstream repository: https://github.com/mtvpls/MoonTVPlus
- Patch base recorded in `custom/CUSTOM_VERSION`
- Custom UI version: 1.7.1

The automation repository stores a patch and build scripts rather than a copied
MoonTVPlus source tree. During CI it checks out the upstream project and applies
the custom patch.

Preserve applicable upstream copyright and license notices in redistributed
derivative builds.
