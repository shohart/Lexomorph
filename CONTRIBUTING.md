# 🤝 Contributing

Issues and pull requests are welcome to Lexomorph (formerly SuperDictate
Next). Please keep changes focused, keep audio on the device, document any new
network use in the README privacy table and PRIVACY.md, and test on macOS 14 or
newer (Apple Silicon or Intel) and, for Windows changes, on Windows 10 1809 or
newer. Since 0.10.0 the macOS identifiers (bundle ID `com.local.lexomorph`,
`Lexomorph.app`, the data paths) carry the new name; the repository, the sync
server address and the Windows build keep the old one on purpose; see
[docs/branding/MIGRATION_NOTES.md](docs/branding/MIGRATION_NOTES.md) before
renaming anything. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community guidelines.

## ✅ Before opening a pull request

```bash
./scripts/check.sh
swift run -c debug --package-path swift Lexomorph --self-test all
./scripts/build-app.sh ./dist/Lexomorph.app
```

## 🚢 Releasing

The release version in `swift/Info.plist` and `install.sh` must match. Release
assets are immutable: publish a new version instead of replacing an existing
ZIP, then update the pinned SHA-256 in `install.sh`.
