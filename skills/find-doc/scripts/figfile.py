"""Figma .fig 파일(로컬 사본)을 읽어 페이지·프레임·레이어 목록을 만든다. 표준 라이브러리만 쓴다.

.fig = zip { canvas.fig, meta.json, thumbnail.png, images/* }
canvas.fig = b"fig-kiwi" + uint32 버전 + [uint32 길이 + 청크]...
  청크 0: kiwi 스키마 (raw deflate)
  청크 1: kiwi 메시지 (zstd 또는 raw deflate)
메시지의 nodeChanges 가 문서의 모든 노드다 (guid, parentIndex, type, name, textData ...).
"""
import io
import struct
import zipfile
import zlib

# ---------- 압축 ----------

def _inflate(b):
    if b[:4] == b"\x28\xb5\x2f\xfd":
        try:
            from compression import zstd  # Python 3.14+
            return zstd.decompress(b)
        except ImportError:
            try:
                import zstandard  # pip install zstandard (Python 3.13 이하)
                return zstandard.ZstdDecompressor().decompressobj().decompress(b)
            except ImportError:
                raise RuntimeError("zstd 압축 해제가 필요합니다. Python 3.14 이상을 쓰거나 'pip install zstandard' 를 실행하세요.")
    try:
        return zlib.decompress(b, -15)
    except zlib.error:
        return zlib.decompress(b)


# ---------- kiwi 디코더 ----------

class _BB:
    __slots__ = ("b", "i")

    def __init__(self, b):
        self.b, self.i = b, 0

    def byte(self):
        v = self.b[self.i]
        self.i += 1
        return v

    def uint(self):
        r = s = 0
        while True:
            c = self.b[self.i]
            self.i += 1
            r |= (c & 127) << s
            if c < 128:
                return r
            s += 7

    def int(self):
        v = self.uint()
        return (v >> 1) ^ -(v & 1)

    def uint64(self):
        # kiwi 의 64비트 varint: 7비트씩 최대 8바이트, 9번째 바이트는 8비트 전부 (일반 LEB128 과 다르다)
        r = s = 0
        while True:
            c = self.b[self.i]
            self.i += 1
            if s == 56:
                return r | (c << 56)
            r |= (c & 127) << s
            if c < 128:
                return r
            s += 7

    def int64(self):
        v = self.uint64()
        return (v >> 1) ^ -(v & 1)

    def float(self):
        first = self.b[self.i]
        if first == 0:
            self.i += 1
            return 0.0
        bits = int.from_bytes(self.b[self.i:self.i + 4], "little")
        self.i += 4
        bits = ((bits << 23) | (bits >> 9)) & 0xFFFFFFFF
        return struct.unpack("<f", struct.pack("<I", bits))[0]

    def string(self):
        j = self.b.index(0, self.i)
        s = self.b[self.i:j].decode("utf-8", "replace")
        self.i = j + 1
        return s

    def bytes_(self):
        n = self.uint()
        v = self.b[self.i:self.i + n]
        self.i += n
        return v


_BUILTIN = {-1: "bool", -2: "byte", -3: "int", -4: "uint", -5: "float", -6: "string", -7: "int64", -8: "uint64"}


def _schema(b):
    bb = _BB(b)
    defs = []
    for _ in range(bb.uint()):
        name = bb.string()
        kind = bb.byte()  # 0 enum, 1 struct, 2 message
        fields = []
        for _ in range(bb.uint()):
            fname = bb.string()
            ftype = bb.int()
            is_array = bb.byte() == 1
            value = bb.uint()
            fields.append((fname, ftype, is_array, value))
        defs.append((name, kind, fields))
    return defs


class _Decoder:
    # 검색에 필요 없는 큰 필드는 읽되 버린다 (속도·메모리)
    def __init__(self, defs, want=None):
        self.defs = defs
        self.by_name = {d[0]: i for i, d in enumerate(defs)}
        self.enum_vals = {}
        for i, (name, kind, fields) in enumerate(defs):
            if kind == 0:
                self.enum_vals[i] = {f[3]: f[0] for f in fields}
        self.msg_fields = {i: {f[3]: f for f in d[2]} for i, d in enumerate(defs) if d[1] == 2}
        self.want = want or {}

    def read(self, bb, t, path=""):
        if t < 0:
            k = _BUILTIN[t]
            if k == "bool":
                return bb.byte() != 0
            if k == "byte":
                return bb.byte()
            if k == "int":
                return bb.int()
            if k == "uint":
                return bb.uint()
            if k == "int64":
                return bb.int64()
            if k == "uint64":
                return bb.uint64()
            if k == "float":
                return bb.float()
            return bb.string()
        name, kind, fields = self.defs[t]
        if kind == 0:
            return self.enum_vals[t].get(bb.uint())
        if kind == 1:
            keep = self.want.get(name)
            out = {}
            for f in fields:
                v = self._field(bb, f)
                if keep is None or f[0] in keep:
                    out[f[0]] = v
            return out
        keep = self.want.get(name)
        mf = self.msg_fields[t]
        out = {}
        while True:
            fid = bb.uint()
            if fid == 0:
                return out
            f = mf[fid]
            if keep is not None and f[0] not in keep:
                self._skip(bb, f)
            else:
                out[f[0]] = self._field(bb, f)

    def _field(self, bb, f):
        _, ftype, is_array, _ = f
        if is_array:
            if ftype == -2:
                return bb.bytes_()
            return [self.read(bb, ftype) for _ in range(bb.uint())]
        return self.read(bb, ftype)

    def _skip(self, bb, f):
        _, ftype, is_array, _ = f
        if is_array and ftype == -2:
            bb.bytes_()
            return
        n = bb.uint() if is_array else 1
        saved = self.want
        self.want = _SKIP_ALL
        try:
            for _ in range(n):
                self.read(bb, ftype)
        finally:
            self.want = saved


class _SkipAll(dict):
    def get(self, k, d=None):
        return ()


_SKIP_ALL = _SkipAll()

# NodeChange 에서 쓰는 필드만 남긴다
_WANT = {
    "Message": {"nodeChanges", "type"},
    "NodeChange": {"guid", "parentIndex", "type", "name", "textData", "phase"},
    "GUID": None,
    "ParentIndex": None,
    "TextData": {"characters"},
}


def read_nodes(fig_path):
    """.fig(zip) 또는 canvas.fig 경로 → NodeChange dict 목록"""
    with open(fig_path, "rb") as fh:
        raw = fh.read()
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            raw = z.read("canvas.fig")
    if raw[:8] != b"fig-kiwi":
        raise ValueError("fig-kiwi 형식이 아닙니다")
    off, chunks = 12, []
    while off + 4 <= len(raw):
        n = struct.unpack("<I", raw[off:off + 4])[0]
        chunks.append(raw[off + 4:off + 4 + n])
        off += 4 + n
    defs = _schema(_inflate(chunks[0]))
    dec = _Decoder(defs, _WANT)
    msg = dec.read(_BB(_inflate(chunks[1])), dec.by_name["Message"])
    return msg.get("nodeChanges", [])


def _gid(g):
    return f"{g['sessionID']}:{g['localID']}"


def layers(fig_path):
    """페이지 › … › 레이어 경로가 붙은 레이어 목록. (page, page_id, node, name, type, level, path, text)"""
    nodes = read_nodes(fig_path)
    by, kids = {}, {}
    for n in nodes:
        if "guid" not in n or n.get("phase") == "REMOVED":
            continue
        gid = _gid(n["guid"])
        by[gid] = n
        pi = n.get("parentIndex")
        if pi and "guid" in pi:
            kids.setdefault(_gid(pi["guid"]), []).append((pi.get("position", ""), gid))
    for v in kids.values():
        v.sort()
    doc = next((g for g, n in by.items() if n.get("type") == "DOCUMENT"), None)
    out = []

    def walk(gid, page, page_id, stack, level):
        n = by[gid]
        name = (n.get("name") or "").strip()
        text = ((n.get("textData") or {}).get("characters") or "").strip()
        path = " › ".join([page] + stack + [name])
        out.append({"page": page, "page_id": page_id, "node": gid, "name": name[:200], "type": n.get("type"),
                    "level": level, "path": path, "text": text[:300] if text and text != name else ""})
        for _, c in kids.get(gid, []):
            walk(c, page, page_id, stack + [name], level + 1)

    import sys
    sys.setrecursionlimit(10000)
    for _, pg in kids.get(doc, []):
        p = by[pg]
        if p.get("type") != "CANVAS":
            continue
        pname = (p.get("name") or "").strip()
        if pname == "Internal Only Canvas":
            continue
        for _, c in kids.get(pg, []):
            walk(c, pname, pg, [], 0)
    return out


if __name__ == "__main__":
    import json
    import sys
    import time
    t = time.time()
    ls = layers(sys.argv[1])
    print(json.dumps({"layers": len(ls), "secs": round(time.time() - t, 1),
                      "pages": len({l["page_id"] for l in ls}), "sample": ls[:3]}, ensure_ascii=False, indent=1))
