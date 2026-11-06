# Jolt: QNX 8.0 setup on Windows (WSL2)

> **The tested path, as used to build Jolt** on Windows 11, an x64 CPU and WSL 3.0. It uses a dedicated distro on D: so the QNX SDP doesn't fill C:.
>
> 1. `wsl --install Ubuntu-22.04 --name qnx --location D:\WSL\qnx --no-launch`
> 2. `wsl -d qnx -u root -e bash setup/10-provision-root.sh <user>`, then `wsl --terminate qnx`. This creates the user and installs systemd, QEMU, libvirt and Java.
> 3. Install QNX Software Center 2.0.4 (Linux hosts) inside the distro, then SDP 8.0 into `~/qnx800` with the x86_64 and aarch64le targets.
> 4. `wsl -d qnx -u root -e bash setup/11-network-root.sh`. This provides libvirt NAT `virbr0` and `qemu-bridge-helper`. WSL2 distros share one network, so it also removes a stale `virbr0` that another distro left behind.
> 5. `bash setup/13-fix-sshd-auth.sh`. SDP 8.0 ships OpenSSH 10.4, which needs `sshd-auth`, but `mkqnximage`'s `system.build` template omits it. The script patches the template and keeps a `.orig` backup.
> 6. `bash setup/12-build-vm.sh --clean` builds and boots the x86_64 VM. It sets up root SSH by key, so `ssh qnxvm` works.
> 7. `bash setup/run-vm.sh` keeps the VM running in a terminal. QEMU started with `-h` is killed when its WSL session closes.
>
> The steps below are the original generic guide.

Goal: by the end you can build C code for QNX on your Windows PC, run it on a QNX virtual machine (QEMU) and on the Raspberry Pi 5, and see a frozen server hang a client. That is the first thing Jolt detects.

Time: about 2 hours, mostly downloads.

## Before you start

- A Windows 10 or 11 PC with an **Intel or AMD** CPU. QNX doesn't support ARM hosts.
- About 30 GB of free disk space.
- Your myQNX login with the free QNX 8.0 licence deployed.

## Step 1: WSL2 (Windows side)

1. Copy this folder to the PC, for example to `C:\jolt-setup`.
2. Open **PowerShell as Administrator** and run:
   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   C:\jolt-setup\setup\01-install-wsl.ps1
   ```
3. Restart if asked. Open **Ubuntu 22.04** from the Start menu and create a Linux username and password.

## Step 2: Ubuntu packages

1. From your myQNX account, download **QNX Software Center for Linux hosts** (a `.run` file) into your Windows `Downloads` folder.
2. In Ubuntu:
   ```bash
   cp -r /mnt/c/jolt-setup ~/jolt-setup
   bash ~/jolt-setup/setup/02-prepare-ubuntu.sh
   ```
   This installs the build tools, QEMU, libvirt and Python. It also starts the Software Center installer; accept the licence and keep the default path.
3. If the script says systemd was enabled, run `wsl --shutdown` in PowerShell, then reopen Ubuntu.

## Step 3: Install QNX SDP 8.0 (Software Center window)

```bash
~/qnx/qnxsoftwarecenter/qnxsoftwarecenter &
```

1. Sign in with your myQNX account.
2. Click **Add Installation** and choose **QNX Software Development Platform 8.0**.
3. Set the install folder to `~/qnx800`.
4. Under **Advanced installation variants**, select both target architectures, **x86_64** and **aarch64le**.
5. Click **Finish**. If the window is cut off, resize it to reach the button.
6. If you still need the Pi image, also install the package `com.qnx.qnx800.quickstart.rpi5`.

The window appears through WSLg, which Windows 11 has built in. On Windows 10 without WSLg, use the Software Center's command-line tool instead; ask me and I'll give you the exact commands.

## Step 4: Check everything and create the QEMU target

```bash
bash ~/jolt-setup/setup/03-verify-and-make-target.sh
ssh qnxvm            # password: root
```

On the target, try:

```sh
uname -a
pidin | head
pidin channels | head
```

## Step 5: Raspberry Pi 5

1. Find the `.img` file under `~/qnx800` (search for `rpi5`) and copy it to Windows:
   ```bash
   find ~/qnx800 -name "*rpi5*.img"
   cp <that file> /mnt/c/Users/$USER/Downloads/
   ```
   If your Windows username differs from your Linux username, use the Windows one in the path.
2. Write the image to a 32 GB or larger microSD card with **Raspberry Pi Imager** (Use custom), then boot the Pi on **Ethernet**.
3. From Ubuntu, run `ssh qnxpi` (password `qnxuser`). Then change the passwords with `passwd`; root's default is also `root`.

## Step 6: The first Jolt experiment

```bash
cd ~/jolt-setup/demo
./build_and_deploy.sh qnxvm     # or: ./build_and_deploy.sh qnxpi
ssh qnxvm 'sh /tmp/jolt/try_faults.sh'
```

What you should see:

| Phase | Server | Client without timeout | Client with `-t 2000` |
| --- | --- | --- | --- |
| Healthy | RECEIVE-blocked (idle) | Gets replies every second | Gets replies every second |
| Freeze (SIGSTOP) | STOPPED | **Stuck forever** (SEND- or REPLY-blocked) | Prints ETIMEDOUT every 2 s and keeps going |
| Kill (SIGKILL) | Gone | Gets an error, reconnects after restart | Gets an error, reconnects after restart |

**Takeaway:** when a server dies, the kernel tells its clients. When a server hangs, nothing does. Only a timeout saves the client, and Jolt finds every edge in a system where that timeout is missing.

## Troubleshooting

- **`qcc: command not found`:** run `source ~/qnx800/qnxsdp-env.sh`. Step 4 adds this to `~/.bashrc`.
- **No IP for the VM:** run `cd ~/qnxtargets/qnxvm && mkqnximage --getip`. Check that `sudo virsh net-list` shows the `default` network as active.
- **`/dev/kvm` missing:** turn on virtualisation (VT-x / AMD-V) in the BIOS, then run `wsl --shutdown` and reopen Ubuntu. QEMU still works without it, just slowly.
- **`ssh qnxpi` fails:** WSL2 sometimes can't resolve `.local` names. Use the Pi's IP from its Welcome screen, or run `ifconfig` on the Pi, and replace `qnxpi.local` with that IP in `~/.ssh/config`.
- **The `pidin` format letters differ on your build:** run `pidin -h` and send me the output, and I'll adjust `try_faults.sh`.

Untested assumptions: the scripts follow QNX's own documentation and the WSL2 guides. They haven't been run on your PC yet, so send me any error output and I'll fix the script.
