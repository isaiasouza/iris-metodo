"""Presets equivalentes aos do Cutdown Pro (Talking Head, Social Media, Cleanup, Action/Sport, Locked-Off, Whip Pans)."""
from __future__ import annotations

import unittest

import presets
from segmentos import montar_selects
from tests.test_segmentos import DT, quadros_fake

N = 40
NIT = [600.0 + 40.0 * ((i * 7) % 10) for i in range(N)]
NOVOS = ("talking_head", "social_media", "cleanup", "action_sport", "locked_off", "whip_pans")


def clipe(nome, **over):
    q = quadros_fake(N, **{"nitidez": NIT, **over})
    return {"caminho": f"/m/{nome}.MP4", "fps": 24.0, "duracao": N * DT, "amostras_por_s": 1 / DT, "quadros": q}


CLIPES = {
    "parado": clipe("parado"),
    "pan": clipe("pan", cam_dx=[0.15] * N),
    "borrado": clipe("borrado", nitidez=[1000.0] * 20 + [5.0] * 20),
    "assunto": clipe("assunto", movimento_assunto=[0.06] * N),
    "mao": clipe("mao", tremor=[0.12] * N),
}


def selects(preset, *nomes):
    """Trechos que o preset tira de cada clipe: {nome: [trechos]}."""
    p = presets.carregar(preset)
    r = montar_selects([CLIPES[n] for n in nomes], p)
    return {n: [t for t in r["trechos"] if t["caminho"] == CLIPES[n]["caminho"]] for n in nomes}


class TestPresetsCutdown(unittest.TestCase):
    def test_todos_carregam_e_aparecem_na_lista(self):
        for nome in NOVOS:
            self.assertEqual(presets.carregar(nome)["nome"], nome)
            self.assertIn(nome, presets.listar())

    def test_talking_head_quer_camera_parada_e_trecho_longo(self):
        s = selects("talking_head", "parado", "mao")
        self.assertTrue(s["parado"])
        self.assertTrue(all(t["duracao_s"] >= 3.0 for t in s["parado"]))
        self.assertEqual(s["mao"], [])

    def test_social_media_corta_curto(self):
        s = selects("social_media", "parado", "assunto")
        for trechos in s.values():
            self.assertTrue(trechos)
            self.assertLessEqual(len(trechos), 3)
            self.assertTrue(all(t["duracao_s"] <= 8.0 + 1e-9 for t in trechos))
        self.assertGreater(max(t["nota"] for t in s["assunto"]), max(t["nota"] for t in s["parado"]))

    def test_cleanup_pega_so_o_que_tem_problema(self):
        s = selects("cleanup", "parado", "borrado", "mao")
        self.assertEqual(s["parado"], [])
        self.assertEqual([(t["inicio_s"], t["fim_s"]) for t in s["borrado"]], [(5.0, 10.0)])
        self.assertIn("blur", s["borrado"][0]["flags"])
        self.assertIn("tremido", s["mao"][0]["flags"])

    def test_action_sport_quer_assunto_em_movimento(self):
        s = selects("action_sport", "parado", "assunto")
        self.assertEqual(s["parado"], [])
        self.assertTrue(s["assunto"])

    def test_locked_off_so_aceita_camera_parada(self):
        s = selects("locked_off", "parado", "pan", "mao")
        self.assertTrue(s["parado"])
        self.assertEqual(s["pan"], [])
        self.assertEqual(s["mao"], [])

    def test_whip_pans_quer_pan_rapido(self):
        s = selects("whip_pans", "parado", "pan")
        self.assertEqual(s["parado"], [])
        self.assertTrue(s["pan"])
        self.assertTrue(all(t["camera"]["tipo"] == "pan_dir" for t in s["pan"]))
        self.assertTrue(all(t["duracao_s"] <= 4.0 + 1e-9 for t in s["pan"]))


if __name__ == "__main__":
    unittest.main()
