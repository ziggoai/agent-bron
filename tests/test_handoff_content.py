import yaml

from bron.agents_md import render_agents_md
from bron.loader import load


def test_delegate_and_connections_skills_are_published(vault):
    skills = load(vault).skills
    assert {"delegate", "connections"} <= set(skills)


def test_agents_md_has_the_ticket_protocol_and_stays_small(vault):
    text = render_agents_md(load(vault))
    assert "## Tickets" in text
    assert ".bron/bin/bron ticket" in text
    assert "Needs your OK:" in text
    assert len(text.encode()) < 8 * 1024


def test_tickets_board_is_valid_and_hides_chats(vault):
    board = yaml.safe_load((vault.tickets_dir / "Board.base").read_text(encoding="utf-8"))
    names = [view["name"] for view in board["views"]]
    assert names == ["By status", "By assignee", "Chats"]
    assert 'kind != "chat"' in str(board["views"][0]["filters"])
    assert board["views"][0]["groupBy"]["property"] == "status"


def test_manual_index_links_resolve(vault):
    index = (vault.core_manual / "index.md").read_text(encoding="utf-8")
    for page in ("models.md", "permissions.md", "connections.md", "tickets.md"):
        assert f"]({page})" in index
        assert (vault.core_manual / page).is_file()
