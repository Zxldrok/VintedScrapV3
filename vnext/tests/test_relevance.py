from vintedscrap_vnext.models import Listing, UserEvent
from vintedscrap_vnext.profile_service import rebuild_profile
from vintedscrap_vnext.relevance import score_listing


def test_score_listing_rewards_matching_brand_and_price_zone():
    events = [
        UserEvent(
            event_type="favorite_add",
            listing=Listing(
                id="1",
                title="Display OP12 One Piece",
                price=170.0,
                brand="OnePiece",
                condition="Neuf avec étiquette",
                seller="seller_a",
            ),
        ),
        UserEvent(
            event_type="open_link",
            listing=Listing(
                id="2",
                title="One Piece OP12 booster",
                price=160.0,
                brand="OnePiece",
                condition="Neuf avec étiquette",
                seller="seller_a",
            ),
        ),
    ]

    profile = rebuild_profile(events)
    result = score_listing(
        profile,
        Listing(
            id="3",
            title="Display OP12 scellé One Piece",
            price=165.0,
            brand="OnePiece",
            condition="Neuf avec étiquette",
            seller="seller_a",
        ),
    )

    assert result.score >= 70
    assert "marque" in result.explanation.lower()


def test_score_listing_penalizes_far_price():
    events = [
        UserEvent(
            event_type="favorite_add",
            listing=Listing(id="1", title="One Piece OP12", price=100.0, brand="OnePiece"),
        ),
    ]

    profile = rebuild_profile(events)
    result = score_listing(
        profile,
        Listing(id="2", title="One Piece OP12 premium", price=300.0, brand="OnePiece"),
    )

    assert result.score < 80
    assert "prix dans ta zone" not in result.explanation.lower()
