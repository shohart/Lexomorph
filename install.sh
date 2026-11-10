#!/bin/bash

set -euo pipefail

REPOSITORY="${LEXOMORPH_REPOSITORY:-shohart/SuperDictate-Next}"
RELEASE_VERSION="0.10.0"
# macOS releases are tagged mac-vX.Y.Z (Windows ones win-vX.Y.Z, same repo);
# 0.7.0 and earlier carry the legacy vX.Y.Z tag.
RELEASE_TAG="mac-v0.10.0"
# PLACEHOLDERS until mac-v0.10.0 is published: scripts/verify-release.sh and
# docs/RELEASING.md set the real SHA-256 and source commit. Until then the
# installer fails closed on the checksum.
RELEASE_SHA256="0000000000000000000000000000000000000000000000000000000000000000"
SOURCE_COMMIT="0000000000000000000000000000000000000000"
RELEASE_URL="${LEXOMORPH_RELEASE_URL:-https://github.com/$REPOSITORY/releases/download/$RELEASE_TAG/Lexomorph.zip}"
EXPECTED_SHA256="${LEXOMORPH_RELEASE_SHA256:-$RELEASE_SHA256}"
REF="${LEXOMORPH_REF:-$SOURCE_COMMIT}"
EXPECTED_SOURCE_COMMIT="${LEXOMORPH_SOURCE_COMMIT:-$SOURCE_COMMIT}"
APP_PATH="${LEXOMORPH_APP_PATH:-/Applications/Lexomorph.app}"
BUILD_FROM_SOURCE="${LEXOMORPH_BUILD_FROM_SOURCE:-0}"
NO_OPEN="${LEXOMORPH_NO_OPEN:-0}"
AGENT_LABEL="com.local.lexomorph.agent"
# Pre-0.10 installation (SuperDictate). Removed only after the new app is
# verified and in place; its data, defaults and Keychain item stay untouched.
LEGACY_APP_PATH="/Applications/SuperDictate.app"
LEGACY_AGENT_LABEL="com.local.superdictate.agent"
LEGACY_AGENT_PLIST="$HOME/Library/LaunchAgents/$LEGACY_AGENT_LABEL.plist"

say() {
    printf '\033[1;36mLexomorph:\033[0m %s\n' "$*"
}

fail() {
    printf '\033[1;31mLexomorph:\033[0m %s\n' "$*" >&2
    exit 1
}

version_at_least_14() {
    local major
    major="$(sw_vers -productVersion | cut -d. -f1)"
    [[ "$major" =~ ^[0-9]+$ ]] && (( major >= 14 ))
}

run_as_admin() {
    if [[ -w "$(dirname "$APP_PATH")" ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

verify_app() {
    local app="$1"
    local executable="$app/Contents/MacOS/Lexomorph"
    local bundle_id version minimum_system entitlements_file audio_input microphone expected_arch

    [[ -x "$executable" ]] || fail "В архиве нет исполняемого файла Lexomorph."
    bundle_id="$(plutil -extract CFBundleIdentifier raw -o - "$app/Contents/Info.plist")"
    [[ "$bundle_id" == "com.local.lexomorph" ]] || fail "Неверный идентификатор приложения: $bundle_id"
    version="$(plutil -extract CFBundleShortVersionString raw -o - "$app/Contents/Info.plist")"
    [[ "$version" == "$RELEASE_VERSION" ]] || fail "Ожидалась версия $RELEASE_VERSION, получена $version."
    minimum_system="$(plutil -extract LSMinimumSystemVersion raw -o - "$app/Contents/Info.plist")"
    [[ "$minimum_system" == "14.0" ]] || fail "Неожиданная минимальная версия macOS: $minimum_system"
    expected_arch="$(/usr/bin/uname -m)"
    file "$executable" | grep -q "$expected_arch" || fail "Сборка не предназначена для этого Mac (ожидалась архитектура $expected_arch)."
    codesign --verify --deep --strict "$app" || fail "Проверка подписи приложения не прошла."
    entitlements_file="$WORK_DIR/verified-entitlements.plist"
    codesign -d --entitlements :- "$app" > "$entitlements_file" 2>/dev/null
    audio_input="$(/usr/libexec/PlistBuddy -c 'Print :com.apple.security.device.audio-input' "$entitlements_file")"
    microphone="$(/usr/libexec/PlistBuddy -c 'Print :com.apple.security.device.microphone' "$entitlements_file")"
    [[ "$audio_input" == "true" && "$microphone" == "true" ]] || fail "В сборке отсутствуют разрешения микрофона."
}

download_release() {
    local work_dir="$1"
    local archive="$work_dir/Lexomorph.zip"
    local actual

    say "Скачиваю готовую сборку $RELEASE_VERSION..."
    curl --fail --location --silent --show-error --retry 3 --retry-delay 1 --retry-all-errors \
        "$RELEASE_URL" \
        -o "$archive"

    actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
    [[ "$actual" == "$EXPECTED_SHA256" ]] || fail "Контрольная сумма загрузки не совпала."

    ditto -x -k "$archive" "$work_dir/release"
    [[ -d "$work_dir/release/Lexomorph.app" ]] || fail "В релизе нет Lexomorph.app."
    ditto "$work_dir/release/Lexomorph.app" "$work_dir/Lexomorph.app"
}

verify_source_ref() {
    local actual

    [[ "$EXPECTED_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "Ожидался полный 40-символьный SHA исходников."

    actual="$(curl --fail --location --silent --show-error --retry 3 --retry-delay 1 --retry-all-errors \
        "https://api.github.com/repos/$REPOSITORY/commits/$REF" \
        | sed -n 's/^[[:space:]]*"sha":[[:space:]]*"\([0-9a-f]\{40\}\)".*/\1/p' \
        | head -n 1)"

    [[ -n "$actual" ]] || fail "Не удалось проверить коммит исходников $REF."
    [[ "$actual" == "$EXPECTED_SOURCE_COMMIT" ]] || fail "Коммит исходников не совпал: ожидался $EXPECTED_SOURCE_COMMIT, получен $actual."
}

build_from_source() {
    local work_dir="$1"
    local source_dir

    command -v swift >/dev/null 2>&1 || {
        say "Для сборки из исходников нужны бесплатные инструменты Apple. Открываю их установку..."
        xcode-select --install >/dev/null 2>&1 || true
        printf '\nПосле установки снова запустите ту же команду.\n'
        exit 0
    }

    say "Проверяю закреплённый коммит исходного кода..."
    verify_source_ref

    say "Скачиваю открытый исходный код..."
    curl --fail --location --silent --show-error --retry 3 --retry-delay 1 --retry-all-errors \
        "https://github.com/$REPOSITORY/archive/$REF.zip" \
        -o "$work_dir/source.zip"
    ditto -x -k "$work_dir/source.zip" "$work_dir/source"
    source_dir="$(find "$work_dir/source" -mindepth 1 -maxdepth 1 -type d -print -quit)"
    [[ -n "$source_dir" ]] || fail "Не удалось распаковать исходный код."
    "$source_dir/scripts/build-app.sh" "$work_dir/Lexomorph.app"
}

[[ "$(/usr/bin/uname -s)" == "Darwin" ]] || fail "Работает только на macOS."
version_at_least_14 || fail "Нужна macOS 14 или новее."

for command_name in curl ditto shasum plutil file codesign sed head; do
    command -v "$command_name" >/dev/null 2>&1 || fail "Не найдена системная команда: $command_name"
done

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lexomorph-install.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

if [[ "$BUILD_FROM_SOURCE" == "1" ]]; then
    build_from_source "$WORK_DIR"
else
    download_release "$WORK_DIR"
fi

verify_app "$WORK_DIR/Lexomorph.app"
say "Устанавливаю приложение в $APP_PATH..."

if [[ "$APP_PATH" == "/Applications/Lexomorph.app" ]]; then
    /bin/launchctl bootout "gui/$UID/$AGENT_LABEL" >/dev/null 2>&1 || true
    /usr/bin/pkill -x Lexomorph >/dev/null 2>&1 || true
fi

INCOMING="$(dirname "$APP_PATH")/.Lexomorph.install.$$"
BACKUP="$(dirname "$APP_PATH")/.Lexomorph.previous.$$"
run_as_admin rm -rf "$INCOMING"
run_as_admin rm -rf "$BACKUP"
run_as_admin ditto "$WORK_DIR/Lexomorph.app" "$INCOMING"
verify_app "$INCOMING"

if [[ -e "$APP_PATH" ]]; then
    run_as_admin mv "$APP_PATH" "$BACKUP"
fi
if ! run_as_admin mv "$INCOMING" "$APP_PATH"; then
    if [[ -e "$BACKUP" ]]; then
        run_as_admin mv "$BACKUP" "$APP_PATH"
    fi
    fail "Не удалось заменить приложение; предыдущая версия восстановлена."
fi

verify_app "$APP_PATH"
run_as_admin rm -rf "$BACKUP"

if [[ "$APP_PATH" == "/Applications/Lexomorph.app" && ( -e "$LEGACY_APP_PATH" || -e "$LEGACY_AGENT_PLIST" ) ]]; then
    say "Найдена прежняя установка SuperDictate. Убираю приложение и его LaunchAgent (данные и настройки остаются)..."
    /bin/launchctl bootout "gui/$UID/$LEGACY_AGENT_LABEL" >/dev/null 2>&1 || true
    /usr/bin/pkill -f "$LEGACY_APP_PATH/Contents/MacOS/" >/dev/null 2>&1 || true
    rm -f "$LEGACY_AGENT_PLIST"
    run_as_admin rm -rf "$LEGACY_APP_PATH"
    say "Название и пакет изменились (SuperDictate -> Lexomorph): разрешения macOS нужно выдать заново; настройки, словарь и модели перенесутся при первом запуске."
fi

if [[ "$NO_OPEN" == "1" ]]; then
    say "Готово. Проверенная сборка установлена."
else
    say "Готово. Открываю Lexomorph..."
    open "$APP_PATH"
    printf '\n1. Нажмите «Разрешить» для микрофона, универсального доступа и мониторинга ввода.\n'
    printf '2. Дождитесь загрузки локальной модели и статуса «Работает».\n'
    printf '3. Нажмите правый Command и начинайте говорить.\n\n'
fi
