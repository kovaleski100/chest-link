"""Real HTTP/TCP GUI tests and independent PKX summary field vectors."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from server import chest_link_server as pc
from server.interface import Interface
from server import pokemon

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "build/chest-link-cli"
PROBE = Path(os.environ.get("CHEST_LINK_GUI_PROBE", ROOT / "build/gui-tests"))


def entry(gen=0, species=25, form=0, encrypted=False, variant=0):
    """Construct known fields in official PKX layouts, with independent inverse
    permutations. This is not a round trip through either preview decoder.
    """
    p = bytearray(328)
    if gen in (7, 8):
        p[0], p[2] = 1, 255
        p[1] = p[3] = 84 if gen == 7 and species == 25 else species
        p[30 if gen == 7 else 24] = 0x2a
        p[31 if gen == 7 else 25] = 0xaa
    elif gen == 6:
        struct.pack_into("II", p, 0, variant, 0x12345678)
        internal = 277 if species == 252 else species
        struct.pack_into("<H", p, 32, internal)
        struct.pack_into("<H", p, 28, sum(struct.unpack_from("<24H", p, 32)) & 65535)
    else:
        struct.pack_into("<I", p, 0, variant << 13)
        struct.pack_into("<H", p, 8, species)
        struct.pack_into("<HH", p, 12, 12345, 54321)
        if gen <= 1:
            p[64] = form << 3
            struct.pack_into("<I", p, 0, variant << 13)
        elif gen == 5:
            struct.pack_into("<H", p, 36, form)
            struct.pack_into("<I", p, 28, 0x87654321)
        else:
            p[29] = form << 3
            struct.pack_into("<I", p, 24, 0x87654321)
        length = 128 if gen <= 1 else 320 if gen == 5 else 224
        struct.pack_into("<H", p, 6, sum(struct.unpack_from("<"+"H"*(length//2), p, 8)) & 65535)
    if encrypted and gen < 7:
        # Official block order differs from lexicographic order at indexes 3/4
        # and 12..23. Store the inverse permutation explicitly here.
        permutations = ["ABCD","ABDC","ACBD","ADBC","ACDB","ADCB",
                        "BACD","BADC","CABD","DABC","CADB","DACB",
                        "BCAD","BDAC","CBAD","DBAC","CDAB","DCAB",
                        "BCDA","BDCA","CBDA","DBCA","CDBA","DCBA"]
        start, length = (32, 48) if gen == 6 else (8, 128 if gen <= 1 else 320 if gen == 5 else 224)
        index = variant % 24 if gen == 6 else variant % 32
        order = permutations[index % 24]
        original = p[start:start+length]
        block = length // 4
        for dest, letter in enumerate(order):
            source = ord(letter)-ord('A')
            p[start+source*block:start+(source+1)*block] = original[dest*block:(dest+1)*block]
        if gen == 6:
            key = struct.unpack_from("<I", p, 0)[0] ^ struct.unpack_from("<I", p, 4)[0]
            for i in range(32, 80):
                p[i] ^= key >> ((i & 3) * 8) & 255
        else:
            key = struct.unpack_from("<H", p, 6)[0] if gen <= 1 else struct.unpack_from("<I", p, 0)[0]
            for i in range(8, 8+length, 2):
                key = (key * 0x41c64e6d + 0x6073) & 0xffffffff
                p[i] ^= key >> 16 & 255
                p[i+1] ^= key >> 24
    # Opaque padding must survive selecting and transferring a Pokémon.
    return struct.pack("<I", gen) + bytes(p) + b"\x93\xa2\xb1\xc0"


class PreviewTests(unittest.TestCase):
    def probe(self, entries):
        p = subprocess.run([str(PROBE), "preview"], input=b"".join(entries), capture_output=True, check=True)
        return [tuple(map(int, row.split())) for row in p.stdout.splitlines()]

    def test_all_generations_and_every_encrypted_block_order(self):
        entries, expected = [], []
        for gen in range(9):
            variants = range(24 if gen == 6 else 32) if gen < 7 else range(1)
            for v in variants:
                for encrypted in ([False, True] if gen < 7 else [False]):
                    e = entry(gen, 25, encrypted=encrypted, variant=v)
                    entries.append(e)
                    p = pokemon.preview(e)
                    self.assertTrue(p["valid"], (gen, v, encrypted))
                    self.assertEqual(p["species"], 25)
                    self.assertEqual(p["name"], "Pikachu")
                    expected.append((int(p["occupied"]), int(p["valid"]), p["species"], p["form"], p["generation"], int(p["egg"]), int(p["shiny"]), p["sprite"]))
        self.assertEqual(self.probe(entries), expected)

    def test_gen3_internal_species_and_alternate_form_summaries(self):
        entries = [entry(6, 252, encrypted=True, variant=17), entry(0, 479, form=2), entry(5, 898)]
        summaries = [pokemon.preview(e) for e in entries]
        self.assertEqual([(p["species"], p["form"], p["name"]) for p in summaries], [(252, 0, "Treecko"), (479, 2, "Rotom"), (898, 0, "Calyrex")])
        native = self.probe(entries)
        self.assertEqual([p[2] for p in native], [252, 479, 898])
        self.assertEqual([p[7] for p in native], [p["sprite"] for p in summaries])
        self.assertNotEqual(summaries[1]["sprite"], 479)

    def test_unknown_and_empty_records_are_read_only(self):
        bad = bytearray(entry(0));bad[80] ^= 19
        values = [bytes(bad), b"\xff"*336, struct.pack("<I", 0)+b"\xfe"*332]
        before = list(values)
        summaries = [pokemon.preview(e) for e in values]
        self.assertTrue(summaries[0]["occupied"])
        self.assertFalse(summaries[0]["valid"])
        self.assertFalse(summaries[1]["occupied"])
        self.assertFalse(summaries[2]["valid"])
        self.assertEqual([p[1] for p in self.probe(values)], [0,0,0])
        self.assertEqual(values,before)


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chest-interface-")
        self.root = Path(self.temp.name)
        self.mailbox = pc.Mailbox(self.root / "pc", 123456)
        self.server = pc.Server(("127.0.0.1",0), self.mailbox, timeout_seconds=2)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval":.01})
        self.worker.start()
        self.ui = Interface(pc,self.mailbox,self.server.server_address,["192.168.1.101"],0)
        self.ui.start(False)
        self.id = self.upload()
        self.original = {n:(self.mailbox.items/self.id/n).read_bytes() for n in ("bank.bnk","names.json")}

    def tearDown(self):
        self.ui.close();self.server.shutdown();self.server.server_close();self.worker.join();self.mailbox.close();self.temp.cleanup()

    def upload(self, gen=0):
        data=bytearray(b"PKSMBANK"+struct.pack("<II",3,2))
        for b in range(2):
            for s in range(30):
                data.extend(entry(gen if s==2 else 0,species=25+b*108) if s in (0,2,29) else b"\xff"*336)
        names=json.dumps(["Caixa 1 é","Caixa 2"],ensure_ascii=False,separators=(",",":")).encode()
        offer=dict(boxes=2,occupied=6,generations=1|(1<<gen),bankBytes=len(data),namesBytes=len(names),hash=hashlib.sha256(data+names).hexdigest())
        label=b"SoulSilver"
        with socket.create_connection(self.server.server_address,timeout=5) as sock:
            sock.sendall(struct.pack("<8sIII",b"CLMAIL01",1,123456,1));pc.result(sock)
            sock.sendall(struct.pack("<II",2,len(label))+label+pc.offer_encode(offer));reply=pc.result(sock)
            if reply.startswith("STORED "):return reply.split()[1]
            self.assertEqual(reply,"READY");sock.sendall(data+names);return pc.result(sock)

    def request(self,path="/api/state",body=None,auth=True,origin=True,host=None):
        connection=http.client.HTTPConnection("127.0.0.1",self.ui.server.server_port,timeout=10)
        headers={}
        if auth:headers["Authorization"]="Bearer "+self.ui.token
        if body is not None:
            headers["Content-Type"]="application/json"
            if origin:headers["Origin"]=f"http://127.0.0.1:{self.ui.server.server_port}"
        if host:headers["Host"]=host
        connection.request("POST" if body is not None else "GET",path,body=json.dumps(body) if body is not None else None,headers=headers)
        response=connection.getresponse();data=response.read();result=(response.status,data,dict(response.getheaders()));connection.close();return result

    def requeue(self,masks,target=1):
        status,data,_=self.request("/api/requeue",dict(id=self.id,target=target,masks=masks))
        self.assertEqual(status,200,data);return json.loads(data)

    def test_state_and_verified_box_data(self):
        status,data,_=self.request();self.assertEqual(status,200);state=json.loads(data)
        self.assertEqual(state["pin"],"123456");self.assertEqual((state["ds"],state["threeds"]),(0,1));self.assertEqual(state["items"][0]["id"],self.id)
        status,data,_=self.request(f"/api/box?id={self.id}&box=0");self.assertEqual(status,200,data);box=json.loads(data)
        self.assertEqual(box["name"],"Caixa 1 é");self.assertEqual(len(box["pokemon"]),30);self.assertEqual(box["pokemon"][0]["name"],"Pikachu");self.assertFalse(box["pokemon"][1]["occupied"])

    def test_actual_offline_web_assets_and_response_headers(self):
        for path in ["/","/app.js","/style.css","/assets/bg_top.png","/assets/sprites.png"]:
            status,data,headers=self.request(path);self.assertEqual(status,200);self.assertGreater(len(data),100);self.assertEqual(headers["Cache-Control"],"no-store");self.assertIn("frame-ancestors 'none'",headers["Content-Security-Policy"])

    def test_local_interface_auth_origin_and_traversal(self):
        self.assertEqual(self.request(auth=False)[0],401)
        self.assertEqual(self.request(host="evil.example")[0],403)
        self.assertEqual(self.request("/assets/../../chest_link_server.py")[0],404)
        self.assertEqual(self.request("/api/requeue",dict(id=self.id,target=1,masks=[1,0]),origin=False)[0],403)
        self.assertEqual(len(self.mailbox.all_metadata()),1)

    def test_individual_selection_reaches_console_without_changing_original(self):
        result=self.requeue([1<<2,1<<29])
        self.assertEqual((result["boxes"],result["occupied"]),(2,2))
        destination=self.root/"ds"
        run=subprocess.run([str(CLI),"mail-fetch",str(destination),"127.0.0.1","123456","1",result["id"],str(self.server.server_address[1]),"50"],text=True,capture_output=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr);self.assertIn("ACK 1",run.stdout)
        banks=list((destination/"banks").glob("*.bnk"));self.assertEqual(len(banks),1);data=banks[0].read_bytes()
        for box,slot in [(0,2),(1,29)]:
            start=16+(box*30+slot)*336;self.assertEqual(data[start:start+336],self.original["bank.bnk"][start:start+336])
        self.assertEqual(data[16:16+336],b"\xff"*336)
        for name,original in self.original.items():self.assertEqual((self.mailbox.items/self.id/name).read_bytes(),original)
        self.assertTrue(self.mailbox.metadata(result["id"])["delivered"])

    def test_requeue_omits_unselected_boxes_and_supports_both_directions(self):
        ds=self.requeue([0,1]);threeds=self.requeue([0,1],2)
        self.assertEqual(ds["boxes"],1);self.assertNotEqual(ds["id"],threeds["id"])
        for result in [ds,threeds]:
            folder=self.mailbox.items/result["id"];pc.validate_package(folder,self.mailbox.metadata(result["id"])["offer"],result["target"])
            self.assertEqual(json.loads((folder/"names.json").read_text()),["Caixa 2"])
            self.assertEqual((folder/"bank.bnk").read_bytes()[16:352],self.original["bank.bnk"][10096:10432])

    def test_delivered_identical_copy_can_be_explicitly_queued_again(self):
        meta=self.mailbox.metadata(self.id);meta["delivered"]=1;pc.atomic_json(self.mailbox.items/self.id/"meta.json",meta)
        result=self.requeue([0x3fffffff]*2,2)
        self.assertEqual(result["id"],self.id);self.assertEqual(len(self.mailbox.all_metadata()),1);self.assertEqual(self.mailbox.metadata(self.id)["delivered"],0)
        for n,b in self.original.items():self.assertEqual((self.mailbox.items/self.id/n).read_bytes(),b)

    def test_generation_refusal_applies_to_selected_records(self):
        self.id=self.upload(7)  # Gen I storage ID; Chest's supported mask is 0x7f.
        status,data,_=self.request("/api/requeue",dict(id=self.id,target=1,masks=[1<<2,0]));self.assertEqual(status,400);self.assertIn("incompativeis",json.loads(data)["error"])
        result=self.requeue([1,0]);self.assertEqual(result["occupied"],1)

    def test_invalid_slot_masks_do_not_publish(self):
        for masks in [[],[1],[0,0],[True,0],[-1,0],[1<<30,0],[1.5,0],"all"]:
            status,_,_=self.request("/api/requeue",dict(id=self.id,target=1,masks=masks));self.assertEqual(status,400,masks)
        self.assertEqual(len(self.mailbox.all_metadata()),1)

    def test_corruption_is_rejected_after_an_earlier_preview(self):
        self.ui.box(self.id,0)
        file=self.mailbox.items/self.id/"bank.bnk";bad=bytearray(file.read_bytes());bad[80]^=1;file.write_bytes(bad)
        status,data,_=self.request(f"/api/box?id={self.id}&box=0");self.assertEqual(status,400);self.assertIn("SHA-256",json.loads(data)["error"])
        status,_,_=self.request("/api/requeue",dict(id=self.id,target=1,masks=[1,0]));self.assertEqual(status,400);self.assertEqual(len(self.mailbox.all_metadata()),1)

    def test_full_mailbox_keeps_existing_data(self):
        self.mailbox.max_items=1
        status,data,_=self.request("/api/requeue",dict(id=self.id,target=1,masks=[1,0]));self.assertEqual(status,400,data)
        self.assertIn("cheia",json.loads(data)["error"])
        for n,b in self.original.items():self.assertEqual((self.mailbox.items/self.id/n).read_bytes(),b)


if __name__ == "__main__":
    unittest.main()
