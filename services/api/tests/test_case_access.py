from app.case_access import hash_case_token, issue_case_token, verify_case_token
from app.models import CaseContext
from app.repository import SQLiteRepository


def test_case_capability_stores_only_hash_and_cascades(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "capability.sqlite3")
    case = repository.create_case(CaseContext())

    token = issue_case_token(repository, case.id)

    assert repository.get_case_access_token_hash(case.id) == hash_case_token(token)
    assert repository.get_case_access_token_hash(case.id) != token
    assert verify_case_token(repository, case.id, token)
    assert not verify_case_token(repository, case.id, "wrong-token")
    assert repository.delete_case(case.id)
    assert repository.get_case_access_token_hash(case.id) is None
