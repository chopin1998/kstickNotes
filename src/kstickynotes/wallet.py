"""KDE's wallet helper: passwords travel through pipes, never command arguments."""
import hashlib
import shutil
import subprocess


def wallet_password(url, username, password=None):
    query = shutil.which('kwallet-query')
    dbus = shutil.which('qdbus6')
    if not query or not dbus:
        raise RuntimeError('缺少 KDE 钱包工具 kwallet-query 或 qdbus6，请先安装')
    try:
        name = subprocess.run([dbus, 'org.kde.kwalletd6', '/modules/kwalletd6',
                               'org.kde.KWallet.networkWallet'],
                              capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        if not name or '\n' in name:
            raise RuntimeError('KDE 钱包名称无效')
        key = 'webdav-' + hashlib.sha256((url + '\n' + username).encode()).hexdigest()
        command = [query, '-f', 'KStickyNotes', '-w' if password is not None else '-r', key, name]
        result = subprocess.run(command, input=password + '\n' if password is not None else None,
                                capture_output=True, text=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        raise RuntimeError('无法访问 KDE 钱包，请解锁钱包后重试') from None
    if result.returncode:
        raise RuntimeError('KDE 钱包操作失败；首次设置请输入 WebDAV 应用密码，并允许钱包访问')
    if password is not None:
        return password
    secret = result.stdout.removesuffix('\n')
    if not secret:
        raise RuntimeError('钱包中没有此账号的应用密码，请打开同步设置填写')
    return secret
