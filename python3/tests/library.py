"""A library, the app the tests serve besides the WorkTracker: it has no history (`Provenance`)."""


def install(txn):
    """A library: a shelf, a singleton, owning its books by `id`; a book cites books."""
    S = txn.Schemas
    return txn.uid("lib/1").mutations([lambda mu: mu.upsert(lambda u: u.exists([lambda p: p
        .symbols({"Shelf": S.OfObject, "Book": S.OfObject, "OnShelf": S.OfRelation, "Cites": S.OfRelation})
        .spec([
            lambda _: _.OnShelf.name("lib.OnShelf").links([lambda t: t.name("shelf"), lambda t: t.name("book")])
            .properties({"id": S.OfStr}).uniques([["shelf", "id"], ["book"]]),
            lambda _: _.Cites.name("lib.Cites").links([lambda t: t.name("citing"), lambda t: t.name("cited")])
            .properties({"page": S.OfInt}),
            lambda _: _.Shelf.name("lib.Shelf").ref(True).singleton("lib.TheShelf").adjacencies({
                "books": lambda a: a.relation([_.OnShelf]).me("shelf")}),
            lambda _: _.Book.name("lib.Book").ref(True)
            .properties({"name": S.OfStr, "summary": S.OfStr, "pages": S.OfInt, "year": S.OfInt, "isbn": S.OfStr,
                         "language": S.OfStr})
            .adjacencies([
                lambda t: t.name("shelf").relation([_.OnShelf]).me("book").owner(True),
                lambda t: t.name("cites").relation([_.Cites]).me("citing"),
                lambda t: t.relation([_.Cites]).me("cited"),
            ]),
        ])]))])


def seed(txn):
    """Two books on the shelf, the first citing the second."""
    L = txn.lib
    return txn.uid("lib.seed/1").mutations([lambda mu: mu.upsert(lambda u: u.exists([lambda p: p
        .symbols({"shelf": L.Shelf, "sicp": L.Book, "lisp": L.Book})
        .spec([
            lambda _: _.shelf.books({"BK-1": lambda e: e.book(_.sicp), "BK-2": lambda e: e.book(_.lisp)}),
            lambda _: _.sicp.name("SICP").summary("Programs as processes.").pages(657).year(1985).isbn("0262010771")
            .language("en").cites([lambda e: e.cited(_.lisp).page(12)]),
            lambda _: _.lisp.name("LISP 1.5").pages(106),
        ])]))])
