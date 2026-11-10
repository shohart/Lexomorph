## 📝 Summary

<!-- What does this PR change, and why? -->

## ✅ Checklist

- [ ] I read [CONTRIBUTING.md](../CONTRIBUTING.md)
- [ ] Audio stays on the device, and any new network call is optional, documented in the README privacy table and PRIVACY.md, and explained here
- [ ] Tested on macOS 14+ (Apple Silicon or Intel) and/or Windows 10 1809+, as far as the change touches them
- [ ] Ran the pre-PR checks:
  ```bash
  ./scripts/check.sh
  swift run -c debug --package-path swift Lexomorph --self-test all
  ./scripts/build-app.sh ./dist/Lexomorph.app
  ```
- [ ] If this changes the release version, `swift/Info.plist` and `install.sh` match

## 🔗 Related issues

<!-- Closes #... -->
