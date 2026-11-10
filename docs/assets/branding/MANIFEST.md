# Lexomorph brand assets: manifest

Imported unchanged from the owner's brand bundle (`Lexomorph_Brand_Assets/`, 58 files).
Every file was compared with the bundle's own `MANIFEST.json` after copying: 58 of 58 SHA-256 values match.

## What these files are

- All artwork is **raster, generated imagery**. There is **no SVG or other editable vector master** (the bundle's own
  README says so). `source-originals/` holds the unmodified generated PNGs; everything else is an export of them.
- The paths `assets/svg/` and `assets/png/` that `ASSET_GUIDE.md` and `IMPLEMENTATION_TASK_EN.md` describe do not
  exist in the bundle. Feature cards are about 460 x 345 px, not the 1200 x 675 px those documents state.
- These are brand concept images. They are **not screenshots** of the application and must not be presented as such.
- The icons are not wired into the macOS or Windows builds on this stream (documentation only).
- Fonts are not included, and none should be added without a licence check.

## Files

"OK for README" is a judgement against what the code does today (docs/branding/REBRAND_AUDIT.md, section 7).

| Path | Pixels | Bytes | SHA-256 | Purpose | OK for README |
|---|---|---:|---|---|---|
| `features/adaptive-dictation.png` | 471x341 | 147753 | `3d5398dddbec66c38de661a9789180bd66685b9ea8c084b587bb8c1d7be09a98` | feature card | NO: implies adaptation of recognition to the user; the app has none beyond vocabulary hints |
| `features/adaptive-dictation.webp` | 471x341 | 17776 | `4aa641f306a46f6c83842f4fc922c8b1811f2bc4e4b6cfdf5309c4e5599085fb` | feature card (WebP copy) | NO: implies adaptation of recognition to the user; the app has none beyond vocabulary hints |
| `features/correction-learning.png` | 458x341 | 144708 | `d5a05a4e05726a51468b26871bf5545652e1d2355a429c5e78ef02c2fdb0b770` | feature card | yes, with caption: heuristic, short edits, undo, can be disabled |
| `features/correction-learning.webp` | 458x341 | 17454 | `3f22d87703e8aa7597f1473320626f184dc4ca251f720b2f5cf42ee6a954e56e` | feature card (WebP copy) | yes, with caption: heuristic, short edits, undo, can be disabled |
| `features/cross-device-sync.png` | 458x348 | 148403 | `c3f3f060ee5bba241df635b4d58c178638b2741b41841ed188415752a7424c28` | feature card | NO: promises vocabulary, settings and style on all devices, shows a phone; settings are not synced, there is no mobile client, mode/statistics sync is unreleased |
| `features/cross-device-sync.webp` | 458x348 | 18434 | `d12310f29f534de1ada8f7715f00c0f979852d37c05ecc68cdd5c8e7960039f9` | feature card (WebP copy) | NO: promises vocabulary, settings and style on all devices, shows a phone; settings are not synced, there is no mobile client, mode/statistics sync is unreleased |
| `features/feature-grid-1536x1024.png` | 1536x1024 | 1250294 | `3daef15acb8198275d40bad1b13a15daf22df30dcb195f0da0203eca22dd7d23` | all six cards in one image | NO: contains the three cards above |
| `features/feature-grid-1536x1024.webp` | 1536x1024 | 123526 | `b54ff167015b7f2ac8dbc22beadd8798bb48af17413d23f023efc639f926744d` | all six cards in one image (WebP copy) | NO: contains the three cards above |
| `features/local-first-privacy.png` | 460x348 | 143983 | `8e7f710ed7632d070adfec23e4ab22f7ef413269ccdfa9195149787ce3012405` | feature card | NO: "your data stays with you" without caveats; optional endpoint and sync send text off the device |
| `features/local-first-privacy.webp` | 460x348 | 16472 | `6322ba1dc03384f12ebb73f1b824ce6d923bab013d62211eba874c90695207c8` | feature card (WebP copy) | NO: "your data stays with you" without caveats; optional endpoint and sync send text off the device |
| `features/personal-vocabulary.png` | 460x341 | 152452 | `b72317f5e3e178818f725e8970ee48904d93f7ab5ae4119cf0b2370fa505b5b4` | feature card | yes, with caption: replacement rules plus ASR hints, not a guarantee |
| `features/personal-vocabulary.webp` | 460x341 | 19438 | `359ed15d692f517b015f8d31d9defe1cef97222f4a2f95fafee6baf046f6822f` | feature card (WebP copy) | yes, with caption: replacement rules plus ASR hints, not a guarantee |
| `features/style-modes.png` | 471x348 | 159446 | `547f27cf2152b66a88a63eed5707b0547df4285a5407e4d23886954ce3c25013` | feature card | yes, with caption: needs a local LLM or an endpoint, off by default; app mode names differ |
| `features/style-modes.webp` | 471x348 | 19824 | `f19b99cf87264cf73568e5c632f12c744ea0fc50582f993444f6ed9f578a4245` | feature card (WebP copy) | yes, with caption: needs a local LLM or an endpoint, off by default; app mode names differ |
| `icons/final-LM/lexomorph-avatar-1024.png` | 1024x1024 | 815695 | `dfcf30d3136394765a493aef3c89cf567e24e8a5afaca90e3e4b4c6d24524072` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-avatar-256.png` | 256x256 | 55460 | `c88696145d7491ac80d924ceb94b3474c852f540aa9170734c39e1329577c4a2` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-avatar-512.png` | 512x512 | 209059 | `0ef8ca1cbac083799681d88aaa82a74152a7e13cb8765982e782c0e0eaac069a` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-1024.png` | 1024x1024 | 810496 | `2ff8560f07e2ac80660ca832250d7d40a3f8ab2e62057e8ae7e8d87ce580aa3c` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-128.png` | 128x128 | 18715 | `c014adf150e32d935a8989311a68f9915cd89720dc4f0fc9d2e2f38b9369448d` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-16.png` | 16x16 | 839 | `d6a9acbb52c262fcba2afb48fe01b1344617ca79ed284286bd1a2cf21558f457` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-20.png` | 20x20 | 1157 | `ce3627c469475811c840d3642ff8fd0ea1309384f69d31770b1eddda07d9d2b3` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-24.png` | 24x24 | 1511 | `5f5929e5ac3e1b83639bad74fa42aab6748aace96958f9ad3d7e7494503e6835` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-256.png` | 256x256 | 59449 | `3eeaf1cd696d3ae1ffe6eee2b669a7c03587597185f2c4757069dea39a2f50e6` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-32.png` | 32x32 | 2332 | `302dc066f9bb0b5272a3508dc38673faaca407044c6fe1ee4dd05a0825c9906e` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-40.png` | 40x40 | 3220 | `30ecd253e56db7cfcf7fe737682c4e28562e8b8f86c53887437307d6c40bffbb` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-48.png` | 48x48 | 4203 | `122eb572b6d5a88703576cefdd2ae26b49a8360b71021112c2066ef59d1085e0` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-512.png` | 512x512 | 222972 | `b93aa03de589e8709e0083b9c411949b7a70d895c5cf0d8d1671b5f8c3b931f9` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph-icon-64.png` | 64x64 | 6465 | `51a634eabcfdecc21d88fd8b7bbb024d9ff6de6859658f81ee4cab85c8d7f758` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.icns` | icns: 16-1024 (+@2x) | 1847389 | `fcb6f5aa4307c98cff4076f40cf9a7be464f56f8314483e579789329bb5715b2` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.ico` | ico: 16/24/32/48/64/128/256 | 97645 | `916e71bd9f52722e267dfb5896d291753634c0762599e6a2fac2d51702f890e9` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.iconset/icon_128x128.png` | 128x128 | 18715 | `c014adf150e32d935a8989311a68f9915cd89720dc4f0fc9d2e2f38b9369448d` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.iconset/icon_128x128@2x.png` | 256x256 | 59449 | `3eeaf1cd696d3ae1ffe6eee2b669a7c03587597185f2c4757069dea39a2f50e6` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.iconset/icon_16x16.png` | 16x16 | 839 | `d6a9acbb52c262fcba2afb48fe01b1344617ca79ed284286bd1a2cf21558f457` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.iconset/icon_16x16@2x.png` | 32x32 | 2332 | `302dc066f9bb0b5272a3508dc38673faaca407044c6fe1ee4dd05a0825c9906e` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.iconset/icon_256x256.png` | 256x256 | 59449 | `3eeaf1cd696d3ae1ffe6eee2b669a7c03587597185f2c4757069dea39a2f50e6` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.iconset/icon_256x256@2x.png` | 512x512 | 222972 | `b93aa03de589e8709e0083b9c411949b7a70d895c5cf0d8d1671b5f8c3b931f9` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.iconset/icon_32x32.png` | 32x32 | 2332 | `302dc066f9bb0b5272a3508dc38673faaca407044c6fe1ee4dd05a0825c9906e` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.iconset/icon_32x32@2x.png` | 64x64 | 6465 | `51a634eabcfdecc21d88fd8b7bbb024d9ff6de6859658f81ee4cab85c8d7f758` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.iconset/icon_512x512.png` | 512x512 | 65577 | `9bf2c9abbd9529866b91bb2b53293c0c6fd3649630e668bc9c0396b296a26d1f` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/final-LM/lexomorph.iconset/icon_512x512@2x.png` | 1024x1024 | 879383 | `fd3996f7d04573e3afe76ab8d2ca53210220cbb98b55a123f494f80ecabaacf3` | final app icon / derived size | n/a (app icons; not wired into the app by this branch) |
| `icons/previous-versions/v1-wave-1024.png` | 1024x1024 | 877296 | `0ed97eb01b314b389e85e460da1f63540cae41f41a186502dd1ea80afef89581` | earlier icon concept, kept for history | n/a |
| `icons/previous-versions/v2-simplified-1024.png` | 1024x1024 | 803085 | `2e30b83322199ace02ec111596a6dcc18a3d17b3ccc7131a663850ed52126061` | earlier icon concept, kept for history | n/a |
| `icons/previous-versions/v3-LM-1024.png` | 1024x1024 | 841450 | `f1f177e15e4b432a0e77038e6c1b8491adbd9208126185b45930a3b2f7034ed7` | earlier icon concept, kept for history | n/a |
| `readme/readme-hero-1280x640.png` | 1280x640 | 716517 | `6a076de75672b405a306c7302ff0a02a1403ab88afa9162b53174eeb03e05fa5` | README header (used in README.md / README.ru.md) | yes: carries no data claims; but its tag pills read "Adaptive ASR" and the subline says "learns your ... writing style" (see BRAND_GUIDELINES, claims review) |
| `readme/readme-hero-1280x640.webp` | 1280x640 | 50538 | `2424b023d647347f56ea36eea9a375c5098bda49f9c223a7c8c52f5e1d6a9b5f` | README header (used in README.md / README.ru.md) (WebP copy) | yes: carries no data claims; but its tag pills read "Adaptive ASR" and the subline says "learns your ... writing style" (see BRAND_GUIDELINES, claims review) |
| `readme/readme-hero-alternate-1280x640.png` | 1280x640 | 715709 | `662de87030d29f4f0eb28baef062ef3ccf6fc8b408f54aadc8727df616088c35` | alternate README header | same caveats as the main hero |
| `readme/readme-hero-alternate-1280x640.webp` | 1280x640 | 57090 | `debfb8a13bda11a5ac50c6d476aa6268543e79d312c6a446c2a297a5167963eb` | alternate README header (WebP copy) | same caveats as the main hero |
| `social/lexomorph-social-1200x630.png` | 1200x630 | 673120 | `e6b7ed2f43e734763e0be68579554fea2f0fb8f82f36a69572635a513614d158` | 1.91:1 social preview variant (Open Graph) | not for README |
| `social/lexomorph-social-1280x640.png` | 1280x640 | 757430 | `3831d2acc5f99521c52c4c07fd6a413ca2d1ddc83165a9eabe5e865275082028` | GitHub social preview (manual upload) | not for README; upload by the owner (MANUAL_OWNER_ACTIONS) |
| `social/lexomorph-social-1280x640.webp` | 1280x640 | 47962 | `b049efb110134de27b8b5880d071af6f3e1c386f1f5cf99b3a88d0d02dbd0ca7` | GitHub social preview (manual upload) (WebP copy) | not for README; upload by the owner (MANUAL_OWNER_ACTIONS) |
| `source-originals/feature-grid-original.png` | 1536x1024 | 1561377 | `166e8c7ea667d2c0c55f7f000cd8b28ebd0ab2f2f2c4e72b6883a9b61d309059` | unmodified generated original | n/a (source) |
| `source-originals/icon-v1-wave-original.png` | 1254x1254 | 1532235 | `16e40fde9987d2abe9ec59cc36ec382d6aca38399e7f00bea6b8b33774302bd9` | unmodified generated original | n/a (source) |
| `source-originals/icon-v2-simplified-original.png` | 1254x1254 | 1446858 | `c91f6f9c67e815bbe606a865ffede6df6a4d91e9d1163eef7c80ce42458d0b49` | unmodified generated original | n/a (source) |
| `source-originals/icon-v3-LM-original.png` | 1254x1254 | 1498115 | `c11cc5648feb6cfbaf34238c13f7dccd977320ea45f6d0f1461376fefba5bde3` | unmodified generated original | n/a (source) |
| `source-originals/icon-v4-LM-final-original.png` | 1254x1254 | 1469187 | `5e16c26e2e6ad6ff6df89ac8b29683cfbce4a7cd9203f67ce2094d97de97671d` | unmodified generated original | n/a (source) |
| `source-originals/readme-hero-alternate-original.png` | 1774x887 | 1498830 | `cff5f94c77a34828561090ab015dccabd8f53385dbb38b23c2ffdb6b8ff468ff` | unmodified generated original | n/a (source) |
| `source-originals/readme-hero-original.png` | 1774x887 | 1502614 | `f5c4ea92f5f7893fcc5d4d7bddf0c6bb3bade0c7c476fcc04605c371a87a0da0` | unmodified generated original | n/a (source) |
| `source-originals/social-preview-original.png` | 1774x887 | 1622662 | `0a121cfc529be3a624c6eed4d03af92189016372c8c8c651f1ca63723fd94827` | unmodified generated original | n/a (source) |
