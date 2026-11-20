"""Cor do marcador pela própria exportação (terços), como no Cutdown, ou pelas faixas fixas."""
from __future__ import annotations

import copy
import json
import unittest

import davinci
import presets
from exportar import _CORES_OTIO, colorir, cores_dos_trechos, para_otio
from exportar_fcp7 import para_xml
from tests.test_saida import INFO, TRECHOS


def T(nota):
    return {"nota": nota}


class TestCores(unittest.TestCase):
    def test_tercos_da_exportacao(self):
        notas = [0.95, 0.9, 0.85, 0.7, 0.66, 0.65, 0.62, 0.61, 0.6]
        self.assertEqual(cores_dos_trechos([T(n) for n in notas]), ["Green"] * 3 + ["Yellow"] * 3 + ["Blue"] * 3)

    def test_mantem_a_ordem_de_entrada(self):
        self.assertEqual(cores_dos_trechos([T(0.5), T(0.9), T(0.7)]), ["Blue", "Green", "Yellow"])

    def test_empate_fica_com_a_cor_de_cima(self):
        self.assertEqual(cores_dos_trechos([T(0.8), T(0.8), T(0.8), T(0.1)]), ["Green"] * 3 + ["Blue"])

    def test_um_dois_e_nenhum_trecho(self):
        self.assertEqual(cores_dos_trechos([T(0.3)]), ["Green"])
        self.assertEqual(cores_dos_trechos([T(0.3), T(0.2)]), ["Green", "Yellow"])
        self.assertEqual(cores_dos_trechos([]), [])

    def test_modo_fixo_e_modo_invalido(self):
        self.assertEqual(cores_dos_trechos([T(0.85), T(0.65), T(0.3)], "fixa"), ["Green", "Yellow", "Blue"])
        self.assertEqual(cores_dos_trechos([T(0.3), T(0.2)], "fixa"), ["Blue", "Blue"])
        with self.assertRaises(ValueError):
            cores_dos_trechos([T(0.3)], "arco-iris")

    def test_colorir_devolve_copias(self):
        orig = [T(0.3), T(0.2)]
        novos = colorir(orig, "exportacao")
        self.assertEqual([t["cor"] for t in novos], ["Green", "Yellow"])
        self.assertNotIn("cor", orig[0])

    def test_preset_tem_cor_marcador(self):
        self.assertEqual(presets.carregar("imovel")["cor_marcador"], "exportacao")
        p = copy.deepcopy(presets.carregar("imovel"))
        p["cor_marcador"] = "arco-iris"
        with self.assertRaises(ValueError):
            presets._validar(p)

    def test_marcadores_do_davinci_usam_a_cor_do_trecho(self):
        t = {"id": "A_01", "caminho": "/m/A.MP4", "inicio_s": 0.0, "fim_s": 2.0, "nota": 0.3, "motivo": "m",
             "cor": "Green"}
        novos, _, _ = davinci.planejar_marcadores([t], {"/m/A.MP4": (24.0, set())})
        self.assertEqual(novos[0]["cor"], "Green")
        sem_cor = {k: v for k, v in t.items() if k != "cor"}
        novos, _, _ = davinci.planejar_marcadores([sem_cor], {"/m/A.MP4": (24.0, set())})
        self.assertEqual(novos[0]["cor"], "Blue")
        self.assertEqual(davinci.cor_marcador(0.85), "Green")

    def test_otio_e_xml_usam_a_cor_do_trecho(self):
        trechos = [dict(t, cor="Blue") for t in TRECHOS]
        texto = json.dumps(para_otio(trechos, INFO, "S"))
        self.assertEqual(texto.count(f'"color": "{_CORES_OTIO["Blue"]}"'), len(TRECHOS))
        self.assertEqual(para_xml(trechos, INFO, "S").count("<label2>Blue</label2>"), len(TRECHOS))


if __name__ == "__main__":
    unittest.main()
