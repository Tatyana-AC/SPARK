#!/usr/bin/env bash
set -euo pipefail

mount_point="/mnt/usb_drive"

log() {
    printf '%s\n' "$*"
}

resolve_source_spec() {
    local source_spec="$1"

    case "$source_spec" in
        UUID=*)
            printf '/dev/disk/by-uuid/%s\n' "${source_spec#UUID=}"
            ;;
        LABEL=*)
            printf '/dev/disk/by-label/%s\n' "${source_spec#LABEL=}"
            ;;
        PARTUUID=*)
            printf '/dev/disk/by-partuuid/%s\n' "${source_spec#PARTUUID=}"
            ;;
        *)
            printf '%s\n' "$source_spec"
            ;;
    esac
}

is_rw_mount() {
    local options="$1"
    [[ ",$options," == *,rw,* ]]
}

expected_source_spec="$(findmnt --fstab -nro SOURCE --target "$mount_point" 2>/dev/null || true)"
if [[ -z "$expected_source_spec" ]]; then
    log "No fstab entry found for $mount_point"
    exit 0
fi

expected_device="$(resolve_source_spec "$expected_source_spec")"
if [[ ! -e "$expected_device" ]]; then
    log "Expected device for $mount_point is not present: $expected_device"
    exit 0
fi

expected_canonical="$(readlink -f "$expected_device" 2>/dev/null || printf '%s' "$expected_device")"
current_source="$(findmnt -nro SOURCE --target "$mount_point" 2>/dev/null || true)"

if [[ -n "$current_source" ]]; then
    current_canonical="$(readlink -f "$current_source" 2>/dev/null || printf '%s' "$current_source")"
    current_options="$(findmnt -nro OPTIONS --target "$mount_point" 2>/dev/null || true)"

    if [[ "$current_canonical" == "$expected_canonical" ]]; then
        if is_rw_mount "$current_options"; then
            log "$mount_point is already mounted read-write from $current_source"
            exit 0
        fi

        log "Attempting read-write remount for $mount_point"
        mount -o remount,rw "$mount_point" || true
        current_options="$(findmnt -nro OPTIONS --target "$mount_point" 2>/dev/null || true)"
        if is_rw_mount "$current_options"; then
            log "$mount_point remounted read-write"
        else
            log "$mount_point remained non-rw after remount attempt"
        fi
        exit 0
    fi

    log "Replacing stale mount $current_source with $expected_canonical"
    umount "$mount_point" 2>/dev/null || umount -l "$mount_point"
fi

mount "$mount_point"
current_source="$(findmnt -nro SOURCE --target "$mount_point" 2>/dev/null || true)"
current_options="$(findmnt -nro OPTIONS --target "$mount_point" 2>/dev/null || true)"

if ! is_rw_mount "$current_options"; then
    log "Mounted $mount_point without rw; retrying as remount,rw"
    mount -o remount,rw "$mount_point" || true
    current_options="$(findmnt -nro OPTIONS --target "$mount_point" 2>/dev/null || true)"
fi

log "$mount_point now mounted from $current_source with options: $current_options"
