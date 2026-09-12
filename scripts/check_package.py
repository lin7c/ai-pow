"""Build and install a copied source tree, cleaning all generated artifacts."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import venv


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="aipow-package-") as tmp:
        work = Path(tmp)
        source = work / "source"
        shutil.copytree(root, source, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.egg-info", "build", "dist", ".venv"))
        environment = work / "venv"
        venv.create(environment, with_pip=True, system_site_packages=True)
        python = environment / "bin/python"
        subprocess.run([str(python), "-m", "pip", "install", "--no-build-isolation",
                        "--no-deps", "--no-cache-dir", str(source)], check=True, timeout=90)
        result = subprocess.run([str(environment / "bin/aipow"), "--version"],
                                capture_output=True, text=True, check=True, timeout=15)
        assert result.stdout.strip() == "0.2.0", result.stdout
        subprocess.run([str(python), "-c", "import ai_pow, ai_pow_scoring, ai_pow_report; assert ai_pow.APP_VERSION == '0.2.0'; assert ai_pow_scoring.ALGORITHM == 'balanced-v1'; assert callable(ai_pow_report.render)"],
                       cwd=work, check=True, timeout=15)
        print("Installed console entry point: " + result.stdout.strip())


if __name__ == "__main__":
    main()
