import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()

from app import alarms, db, filters, search  # noqa: E402
from app.facebook import parse_cards, search_url  # noqa: E402
from app.marktplaats import parse_item  # noqa: E402

P = search.parse_params({"q": "fiets"})


def item(i, title="Gazelle fiets", flags=(), src="marktplaats"):
    return {"id": i, "source": src, "title": title, "description": "", "flags": list(flags),
            "priceLabel": "€ 100", "city": "Rotterdam", "url": "https://x/" + i, "image": ""}


def test_accessories_are_hidden_compounds_are_kept():
    assert not filters.reasons(item("a", "Damesfiets"), P)
    assert not filters.reasons(item("b", "Bakfietsen"), P)
    assert filters.reasons(item("c", "Fietshelm nieuw"), P) == ["accessoire"]


def test_all_words_must_be_in_title():
    p = search.parse_params({"q": "fiets heren"})
    assert filters.reasons(item("a", "Craft hardloopjack - Maat L"), p) == ["zoekwoord niet in titel"]
    assert not filters.reasons(item("b", "Gazelle herenfiets 28 inch"), p)
    assert not filters.reasons(item("c", "Heren fiets Batavus"), p)


def test_ads_websites_and_hidden_words():
    assert "advertentie" in filters.reasons(item("a", flags=["advertentie"]), P)
    assert "link naar website" in filters.reasons(item("b", flags=["website"]), P)
    assert "door jou verborgen" in filters.reasons(item("c"), P, {"c"})
    p = search.parse_params({"q": "fiets", "exclude": "Gezocht, kapot"})
    assert filters.reasons(item("d", "Fiets kapot"), p) == ['bevat "kapot"']
    off = search.parse_params({"q": "fiets", "noAds": "0"})
    assert not filters.reasons(item("e", flags=["advertentie"]), off)


def test_parse_marktplaats_item():
    it = parse_item({"itemId": "m123", "title": "Fiets", "priceInfo": {"priceCents": 12500, "priceType": "FIXED"},
                     "vipUrl": "/v/fiets/m123", "location": {"cityName": "Delft", "distanceMeters": 4200},
                     "sellerInformation": {"sellerWebsiteUrl": "https://shop.nl"}}, 0)
    assert it["id"] == "mp-m123" and it["priceLabel"] == "€ 125" and it["distanceKm"] == 4.2
    assert it["url"] == "https://www.marktplaats.nl/v/fiets/m123" and "website" in it["flags"]
    assert parse_item({"itemId": "m1", "priceInfo": {"priceType": "FREE"}}, 0)["priceLabel"] == "Gratis"


def test_parse_facebook_cards_and_url():
    items = parse_cards([
        {"href": "https://www.facebook.com/marketplace/item/42/?x=1", "img": "i", "lines": ["€150", "Fiets", "Breda"]},
        {"href": "https://www.facebook.com/marketplace/item/42/", "img": "", "lines": ["€150", "Fiets"]},
        {"href": "https://www.facebook.com/marketplace/item/43/", "img": "", "lines": ["Gratis", "Stoel"]},
        {"href": "/marketplace/np/item/44/?location_id=rotterdam", "img": "", "lines": ["€ 85", "Fiets Gazelle"]},
    ])
    assert [i["id"] for i in items] == ["fb-42", "fb-43", "fb-44"]
    assert items[0]["price"] == 150 and items[0]["city"] == "Breda" and items[1]["priceLabel"] == "Gratis"
    assert "creation_time_descend" in search_url({"q": "fiets", "sort": "newest", "city": "Den Haag"})
    assert "/marketplace/np/denhaag/search" in search_url({"q": "fiets", "city": "Den Haag"})


def test_alarm_first_run_seeds_then_reports_only_new(monkeypatch):
    results = {"v": [item("mp-1"), item("mp-2")]}
    monkeypatch.setattr(search, "fetch", lambda src, p, fresh=True: [dict(i) for i in results["v"]])
    aid = db.add_alarm("fiets", dict(P, sources=["marktplaats"]), ["browser"], 10)

    found, errors, seeded = alarms.new_items(db.get_alarm(aid))
    assert found == [] and seeded == {"marktplaats"}      # first run: nothing reported
    db.finish_run(aid, seeded, 0, "")

    results["v"] = [item("mp-3"), item("mp-4", "Fietshelm"), item("mp-1"), item("mp-5", flags=["advertentie"])]
    found, _, _ = alarms.new_items(db.get_alarm(aid))
    assert [i["id"] for i in found] == ["mp-3"]           # accessory and ad filtered, old one skipped

    found, _, _ = alarms.new_items(db.get_alarm(aid))
    assert found == []                                    # nothing reported twice


def test_failing_source_does_not_seed_or_block_the_other(monkeypatch):
    def fake(src, p, fresh=True):
        if src == "facebook":
            raise RuntimeError("Facebook: niet ingelogd")
        return [item("mp-1")]
    monkeypatch.setattr(search, "fetch", fake)
    aid = db.add_alarm("fiets", dict(P, sources=["marktplaats", "facebook"]), ["browser"], 10)
    _, errors, seeded = alarms.new_items(db.get_alarm(aid))
    assert seeded == {"marktplaats"} and "niet ingelogd" in errors[0]


def test_cycling_clothes_are_not_bikes():
    p = search.parse_params({"q": "heren fiets"})
    assert filters.reasons(item("a", "Craft fietsshirt heren"), p) == ["accessoire"]
    assert filters.reasons(item("b", "Heren fietsshirtjes set"), p) == ["accessoire"]
    assert not filters.reasons(item("c", "Gazelle herenfiets 28 inch"), p)
    assert not filters.reasons(item("d", "Heren fiets Batavus"), p)
    assert not filters.reasons(item("e", "Herenfietsen te koop"), p)


def test_wheel_and_frame_size():
    it = lambda t: item("x", t)
    assert filters.specs(it("Batavus 28 inch, framemaat 58 cm")) == {"wheel": [28.0], "frame": [58]}
    assert filters.specs(it('Racefiets 700c frame 54')) == {"wheel": [28.0], "frame": [54]}
    assert filters.specs(it("Mountainbike 27,5\" maat 52")) == {"wheel": [27.5], "frame": [52]}
    assert filters.specs(it("Fiets voor 180 cm lengte")) == {"wheel": [], "frame": []}
    p = search.parse_params({"q": "fiets", "wheel": "28", "frameMin": "56"})
    assert not filters.reasons(item("a", "Fiets 28 inch frame 58"), p)
    assert filters.reasons(item("b", "Fiets 26 inch frame 58"), p) == ["wielmaat 26 inch"]
    assert filters.reasons(item("c", "Fiets 28 inch frame 52"), p) == ["frame 52 cm (te klein)"]
    assert not filters.reasons(item("d", "Gewone fiets"), p)                      # unknown stays
    strict = search.parse_params({"q": "fiets", "wheel": "28", "frameMin": "56", "needSize": "1"})
    assert filters.reasons(item("d", "Gewone fiets"), strict) == ["wielmaat onbekend", "framemaat onbekend"][:1] + ["framemaat onbekend"]


def test_require_words():
    p = search.parse_params({"q": "fiets", "require": "7 versnellingen, Gazelle"})
    assert filters.reasons(item("a", "Gazelle fiets 7 versnellingen"), p) == []
    assert filters.reasons(item("b", "Batavus fiets 7 versnellingen"), p) == ['mist "gazelle"']
