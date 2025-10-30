#!/usr/bin/env python3
import asyncio
from telethon import TelegramClient
import argparse
import json
from pathlib import Path

# Constants
SESSION_NAME = "jtools.session"
CONFIG_FILE = "jtools_config.json"

class TGConfig:
    def __init__(self, file):
        # accept either Path or str
        self.config_path = Path(file)
        if self.config_path.exists():
            with self.config_path.open("r") as f:
                cfg = json.load(f)
            try:
                self.api_id = int(cfg.get("api_id"))
            except (TypeError, ValueError):
                raise ValueError("Invalid or missing 'api_id' in config")
            self.api_hash = cfg.get("api_hash")
            if not self.api_hash:
                raise ValueError("Missing 'api_hash' in config")
        else:
            try:
                self.api_id = int(input("Enter Telegram API ID: ").strip())
            except Exception:
                raise ValueError("API ID must be an integer")
            self.api_hash = input("Enter Telegram API hash: ").strip()
            dir_ = self.config_path.parent
            if dir_:
                dir_.mkdir(parents=True, exist_ok=True)
            with self.config_path.open("w") as f:
                json.dump({"api_id": self.api_id, "api_hash": self.api_hash}, f, indent=2)

    def get_client(self):
        return TelegramClient(SESSION_NAME, self.api_id, self.api_hash)
    

def _build_parser():
    parser = argparse.ArgumentParser(prog="jtools", description="Johnny's porn upload tools")
    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")

    # whoami
    p = subparsers.add_parser("whoami", help="Show current logged in user")
    p.set_defaults(func=_cmd_whoami)

    # convert_vids
    p = subparsers.add_parser("convert-vids", help="Convert video files")
    p.add_argument("folder", help="Input video folder")
    p.set_defaults(func=_cmd_convert_vids)

    # split large videos into n equal parts
    p = subparsers.add_parser("split-vids", help="Split large video files into smaller parts")
    p.add_argument("folder", help="Input video folder")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--num-parts", "-n", type=int, help="Number of parts to split into")
    grp.add_argument("--part-size-gb", "-s", type=float, help="Target part size in GB (split files into as many parts as needed)")
    p.add_argument("--size-to-split", type=float, default=0, help="Size threshold (in MB) to split files larger than this (default 0 MB)")
    p.set_defaults(func=_cmd_split_vids)

    # use telegram-upload to upload videos with the -a flag, deleting them afterwards if successful
    p = subparsers.add_parser("upload-vids", help="Upload video files using telegram-upload")
    p.add_argument("folder", help="Input video folder")
    p.add_argument("--album", action="store_true", help="Upload as album")
    # capture any remaining flags/arguments and forward them to telegram-upload
    p.add_argument("extra_args", nargs=argparse.REMAINDER, help="Additional flags forwarded to telegram-upload")
    p.set_defaults(func=_cmd_upload_vids)

    return parser

async def _cmd_whoami(args, cfg):
    client = cfg.get_client()
    await client.start()
    me = await client.get_me()
    print(f"id: {me.id}")
    if getattr(me, "username", None):
        print(f"username: @{me.username}")
    if getattr(me, "first_name", None):
        print(f"name: {me.first_name} {getattr(me, 'last_name', '')}".strip())
    await client.disconnect()

async def _cmd_convert_vids(args, cfg):
    import subprocess
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: {folder} is not a directory")
        return
    for file in folder.iterdir():
        if file.suffix.lower() == ".mp4":
            continue
        if file.suffix.lower() not in [".mov", ".avi", ".mkv"]:
            continue
        output_file = file.with_suffix(".mp4")
        cmd = [
            "ffmpeg",
            "-i", str(file),
            "-c", "copy",
            str(output_file)
        ]
        print(f"Converting {file} to {output_file}...")
        result = subprocess.run(cmd)
        if result.returncode == 0:
            file.unlink()  # Delete original file
            print(f"Finished converting {file}")
        else:
            print(f"Error converting {file}")

async def _cmd_split_vids(args, cfg):
    import subprocess
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: {folder} is not a directory")
        return
    for file in folder.iterdir():
        if file.suffix.lower() != ".mp4":
            continue
        if args.num_parts is not None:
            # Split by number of parts
            n = args.num_parts
            if file.stat().st_size <= args.size_to_split * 1024 * 1024:
                continue
            # Get duration of the video
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error getting duration of {file}")
                continue
            duration = float(result.stdout.strip())
            part_duration = duration / n
            for i in range(n):
                start_time = i * part_duration
                output_file = file.with_name(f"{file.stem} (part {(i+1):02}){file.suffix}")
                cmd = [
                    "ffmpeg",
                    "-i", str(file),
                    "-ss", str(start_time),
                    "-t", str(part_duration),
                    "-c", "copy",
                    str(output_file)
                ]
                print(f"Creating part {i+1} of {file} as {output_file}...")
                result = subprocess.run(cmd)
                if result.returncode != 0:
                    print(f"Error creating part {i+1} of {file}")
                    break
            else:
                file.unlink()  # Delete original file after successful split
                print(f"Finished splitting {file}")
        elif args.part_size_gb is not None:
            # Split by part size
            part_size_bytes = args.part_size_gb * 1024 * 1024 * 1024
            if file.stat().st_size <= args.size_to_split * 1024 * 1024:
                continue
            # Get duration of the video
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error getting duration of {file}")
                continue
            duration = float(result.stdout.strip())
            num_parts = int(file.stat().st_size / part_size_bytes) + 1
            part_duration = duration / num_parts
            for i in range(num_parts):
                start_time = i * part_duration
                output_file = file.with_name(f"{file.stem} (part {(i+1):02}){file.suffix}")
                cmd = [
                    "ffmpeg",
                    "-i", str(file),
                    "-ss", str(start_time),
                    "-t", str(part_duration),
                    "-c", "copy",
                    str(output_file)
                ]
                print(f"Creating part {i+1} of {file} as {output_file}...")
                result = subprocess.run(cmd)
                if result.returncode != 0:
                    print(f"Error creating part {i+1} of {file}")
                    break
            else:
                file.unlink()  # Delete original file after successful split
                print(f"Finished splitting {file}")


async def _cmd_upload_vids(args, cfg):
    import subprocess
    import re
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: {folder} is not a directory")
        return

    video_files = list(folder.glob("*.mp4"))
    if not video_files:
        print("No .mp4 files found in the specified folder.")
        return

    if args.album:
        # Original album behavior
        cmd = ["telegram-upload", "--album"]
        if args.extra_args:
            cmd.extend(args.extra_args)
        cmd.append(str(folder / "*.mp4"))
        print(f"Uploading all videos as album from {folder}...")
        result = subprocess.run(cmd)
        if result.returncode == 0:
            for file in video_files:
                file.unlink()
            print("Upload completed and files deleted successfully.")
        else:
            print("Error during upload.")
        return

    # Group files by base name (without part numbers)
    part_groups = {}
    standalone_files = []
    part_pattern = re.compile(r'(.*?)\s*\(part\s+\d+\)\.mp4$')
    
    for file in video_files:
        match = part_pattern.match(file.name)
        if match:
            base_name = match.group(1)
            if base_name not in part_groups:
                part_groups[base_name] = []
            part_groups[base_name].append(file)
        else:
            standalone_files.append(file)

    # Upload part groups as albums
    for base_name, files in part_groups.items():
        files.sort(key=lambda f: int(re.search(r'part\s+(\d+)', f.name).group(1)))
        cmd = ["telegram-upload", "--album"]
        if args.extra_args:
            cmd.extend(args.extra_args)
        cmd.extend(str(f) for f in files)
        
        print(f"Uploading parts of {base_name} as album...")
        result = subprocess.run(cmd)
        if result.returncode == 0:
            for file in files:
                file.unlink()
            print(f"Uploaded and deleted parts of {base_name}")
        else:
            print(f"Error uploading parts of {base_name}")

    # Upload remaining files individually
    for file in standalone_files:
        cmd = ["telegram-upload", "-d"]
        if args.extra_args:
            cmd.extend(args.extra_args)
        cmd.append(str(file))
        
        print(f"Uploading {file.name}...")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"Error uploading {file.name}")


def main():
    parser = _build_parser()
    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        return

    cfg_path = Path(__file__).resolve().parent / CONFIG_FILE
    cfg = TGConfig(cfg_path)
    # dispatch async command
    asyncio.run(args.func(args, cfg))

if __name__ == "__main__":
    main()
    