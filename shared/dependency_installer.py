# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""
Dependency installer for missing Python packages in QGIS environment.

Detects missing packages and installs them via pip in-process.
Designed for QGIS's embedded Python where sys.executable is the QGIS
binary, not the Python interpreter.
"""

import importlib
import io
import sys
from contextlib import redirect_stdout, redirect_stderr

from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from .logger import log_info, log_warning, log_success
from .compat import MsgBoxYes, MsgBoxNo


def is_package_available(import_name: str) -> bool:
    """Check if a Python package can be imported.

    Args:
        import_name: module name used in import statement (e.g. 'psycopg2')
    """
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def _find_pip_main():
    """Return pip's main entry point, handling different pip versions.

    Modern pip (>=22) exposes main in pip._internal.cli.main.
    Older pip (>=10,<22) exposes it in pip._internal.
    Very old pip exposes pip.main directly.
    """
    candidates = [
        "pip._internal.cli.main:main",
        "pip._internal:main",
        "pip:main",
    ]
    for spec in candidates:
        module_name, _, attr_name = spec.partition(":")
        try:
            module = importlib.import_module(module_name)
            return getattr(module, attr_name)
        except Exception as exc:
            log_warning(f"dependency_installer: pip candidate {spec} failed: {exc}")
            continue
    return None


def _run_pip_install(pip_name: str) -> tuple:
    """Execute pip install in-process.

    Uses pip's own API to avoid subprocess + sys.executable issues in
    QGIS (where sys.executable is qgis-bin.exe, not python).
    Captures stdout/stderr so pip's verbose output doesn't pollute the
    QGIS console.

    Returns:
        (success: bool, message: str)
    """
    pip_main = _find_pip_main()
    if pip_main is None:
        log_info("dependency_installer: pip not directly available, bootstrapping")
        try:
            import ensurepip
            ensurepip.bootstrap(upgrade=True)
            pip_main = _find_pip_main()
        except Exception as exc:
            return False, f"pip unavailable and ensurepip failed: {exc}"

    if pip_main is None:
        return False, "pip could not be loaded"

    log_info(f"dependency_installer: pip install {pip_name} starting")

    base_args = ["install", "--no-input", pip_name]
    attempts = [
        ("default", base_args),
        ("user", base_args + ["--user"]),
    ]

    for mode, args in attempts:
        log_info(f"dependency_installer: attempt mode={mode} args={args}")
        out = io.StringIO()
        err = io.StringIO()
        try:
            saved_argv = sys.argv[:]
            sys.argv = ["pip"] + args
            with redirect_stdout(out), redirect_stderr(err):
                result = pip_main(args)
            sys.argv = saved_argv
            pip_stdout = out.getvalue().strip()
            pip_stderr = err.getvalue().strip()
            success = (result == 0)
            if success:
                msg = f"pip install {pip_name} mode={mode} exit_code=0"
                log_success(f"dependency_installer: {msg}")
                return True, msg
            # If package is already satisfied, consider success but keep trying
            # only if the import is still missing (handled by caller).
            log_warning(
                f"dependency_installer: pip mode={mode} failed "
                f"exit_code={result} stdout={pip_stdout!r} stderr={pip_stderr!r}"
            )
        except SystemExit as exc:
            sys.argv = saved_argv
            code = getattr(exc, "code", 1)
            if code == 0 or code is None:
                return True, f"pip install {pip_name} mode={mode} SystemExit ok"
            log_warning(
                f"dependency_installer: pip mode={mode} SystemExit code={code}"
            )
        except Exception as exc:
            sys.argv = saved_argv
            log_warning(f"dependency_installer: pip mode={mode} exception: {exc}")

    return False, f"pip install {pip_name} failed after default and --user attempts"


def install_dependency(
    import_name: str,
    pip_name: str,
    display_name: str,
    parent: QWidget = None,
) -> bool:
    """Install a missing Python package with user confirmation.

    Runs pip install synchronously. The UI will freeze during installation
    (~10-30s). This is acceptable vs the alternative of QgsTask subclassing
    which causes segfaults on plugin reload in QGIS.

    Args:
        import_name: module name for import check (e.g. 'psycopg2')
        pip_name: pip package name to install (e.g. 'psycopg2-binary')
        display_name: human-readable name for dialog text
        parent: parent widget for QMessageBox

    Returns:
        True if package is importable after installation
    """
    if is_package_available(import_name):
        log_info(f"dependency_installer: {display_name} already available")
        return True

    reply = QMessageBox.question(
        parent,
        "Installer la dépendance manquante",
        f"La bibliothèque '{display_name}' est requise pour les fonctionnalités PostgreSQL.\n\n"
        f"Installer '{pip_name}' maintenant via pip ?",
        MsgBoxYes | MsgBoxNo,
        MsgBoxYes,
    )

    if reply != MsgBoxYes:
        log_warning(f"dependency_installer: user declined install of {display_name}")
        return False

    success, msg = _run_pip_install(pip_name)

    if not success:
        QMessageBox.critical(
            parent,
            "Échec de l'installation",
            f"Impossible d'installer {display_name} :\n{msg}\n\n"
            f"Vous pouvez l'installer manuellement avec :\n"
            f"  pip install {pip_name}",
        )
        return False

    if is_package_available(import_name):
        log_success(f"dependency_installer: {display_name} installed and verified")
        QMessageBox.information(
            parent,
            "Installation réussie",
            f"{display_name} a été installé avec succès.\n"
            f"Redémarrez QGIS pour activer les fonctionnalités PostgreSQL.",
        )
        return True

    log_warning(f"dependency_installer: pip succeeded but import still fails for {display_name}")
    QMessageBox.warning(
        parent,
        "Vérification post-installation",
        f"pip a terminé l'installation mais {display_name} n'a pas pu être importé.\n"
        f"Redémarrez QGIS puis rouvrez le plugin.",
    )
    return False
