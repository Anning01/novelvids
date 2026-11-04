from pathlib import Path
import tarfile
from unittest.mock import patch

import pytest

from scripts.prune_deployment_backups import cleanup_targets, remove_targets, validate_backup


def bundle(root: Path) -> Path:
    keep = root / 'novelvids-deploy-backups/release-6841ac4-20261023192335'
    (keep / 'dist').mkdir(parents=True)
    (keep / 'dist/index.html').write_text('previous frontend')
    (keep / 'previous-commit').write_text('a' * 40)
    (keep / 'database.dump').write_bytes(b'backup')
    main = root / 'main.py'
    main.write_text('previous code')
    with tarfile.open(keep / 'code.tar.gz', 'w:gz') as archive:
        archive.add(main, arcname='main.py')
    return keep


def test_cleanup_keeps_live_data_other_projects_and_exactly_one_release(tmp_path):
    keep = bundle(tmp_path)
    live = ['novelvids/media/clip.mp4', 'novelvids/.venv/bin/python', 'cert/site.pem',
            'ai-software-distribution-platform/app.py', 'backups/other-app/data.dump',
            'deploy-backups/new-qiling-retired/environment.saved']
    old = ['novelvids-dependency-backup.old/venv/file', 'novelvids-web-dist-old.tar.gz',
           'novelvids-releases/old/index.html', 'novelvids-deploy-artifacts/new.tar.gz',
           'novelvids-deploy-backups/old/database.dump', 'deploy-backups/novelvids/dist-old/file',
           'backups/novelvids-postgres-old/database.dump', 'backups/.novelvids-postgres-current']
    for relative in live + old:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('keep or delete')
    with patch('scripts.prune_deployment_backups.subprocess.run') as check:
        assert validate_backup(tmp_path, keep.name) == keep
        check.assert_called_once()
    remove_targets(cleanup_targets(tmp_path, keep))
    assert list(keep.parent.iterdir()) == [keep]
    assert all((tmp_path / relative).exists() for relative in live)
    assert all(not (tmp_path / relative).exists() for relative in old)
    assert cleanup_targets(tmp_path, keep) == []


def test_missing_database_or_unsafe_release_refuses_cleanup(tmp_path):
    keep = bundle(tmp_path)
    (keep / 'database.dump').unlink()
    with pytest.raises(ValueError):
        validate_backup(tmp_path, keep.name)
    with pytest.raises(ValueError):
        validate_backup(tmp_path, '../novelvids')


def test_symlink_parent_is_not_followed(tmp_path):
    keep = bundle(tmp_path)
    outside = tmp_path / 'unrelated'
    outside.mkdir()
    (tmp_path / 'backups').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        cleanup_targets(tmp_path, keep)
