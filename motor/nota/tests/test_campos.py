"""Campos de marcador novos: as submétricas, o resumo delas e as estrelas."""
from __future__ import annotations

import copy
import unittest

import presets
from segmentos import trechos_do_clipe, valores_trecho
from tests.test_segmentos import DT, preset, quadros_fake

SUB = {"nitidez": 0.91, "detalhe": 0.5, "estab_foco": 0.7, "folga_cor": 0.88, "flicker": 0.31, "luma": 0.8,
       "contraste": 0.6, "camera": 0.65, "assunto": 0.12, "estab_movimento": 0.55}


def trecho(**over):
    t = {"id": "A_01", "caminho": "/m/A.MP4", "nota": 0.84, "duracao_s": 4.0, "inicio_s": 0.0, "fim_s": 4.0,
         "camera": {"tipo": "parada", "confianca": 0.9}, "flags": [], "motivo": "m", "direcao": None, "pico": 0.9,
         "metricas": {"foco": 0.9, "exposicao": 0.8, "estabilidade": 0.7, "movimento": 0.6}, "submetricas": dict(SUB)}
    t.update(over)
    return t


class TestCampos(unittest.TestCase):
    def test_submetricas_uma_a_uma_e_resumo(self):
        v = valores_trecho(trecho())
        self.assertEqual(v["sub_nitidez"], "0,91")
        self.assertEqual(v["sub_camera"], "0,65")
        self.assertEqual(v["sub_estab_movimento"], "0,55")
        self.assertEqual(v["camera"], "parada")   # o tipo de câmera continua no {camera}
        self.assertEqual(v["submetricas"], "nitidez 0,91 · folga_cor 0,88 · luma 0,80 / flicker 0,31 · assunto 0,12")

    def test_sem_submetricas_mostra_traco(self):
        for t in (trecho(submetricas={}), {k: v for k, v in trecho().items() if k != "submetricas"}):
            v = valores_trecho(t)
            self.assertEqual(v["sub_nitidez"], "—")
            self.assertEqual(v["submetricas"], "—")

    def test_poucas_submetricas(self):
        v = valores_trecho(trecho(submetricas={"nitidez": 0.9, "luma": 0.4}))
        self.assertEqual(v["submetricas"], "nitidez 0,90 · luma 0,40")
        self.assertEqual(v["sub_detalhe"], "—")

    def test_estrelas_pela_nota(self):
        casos = {0.0: "★☆☆☆☆", 0.29: "★☆☆☆☆", 0.3: "★★☆☆☆", 0.5: "★★★☆☆", 0.84: "★★★★☆", 0.9: "★★★★★", 1.0: "★★★★★"}
        for nota, esperado in casos.items():
            self.assertEqual(valores_trecho(trecho(nota=nota))["estrelas"], esperado, nota)

    def test_estrela_so_no_melhor_do_clipe(self):
        self.assertEqual(valores_trecho(trecho(melhor_do_clipe=True))["estrela"], "★")
        self.assertEqual(valores_trecho(trecho(melhor_do_clipe=False))["estrela"], "")
        self.assertEqual(valores_trecho(trecho())["estrela"], "")

    def test_campos_novos_valem_no_preset(self):
        for campo in ("estrela", "estrelas", "submetricas", "sub_nitidez", "sub_estab_movimento"):
            self.assertIn(campo, presets.CAMPOS_TRECHO)
        p = copy.deepcopy(presets.carregar("imovel"))
        p["campos"] = {"marcador_nome": "{estrela}{id} {estrelas}", "marcador_nota": "{submetricas} {sub_luma}",
                       "relatorio": ["sub_nitidez", "estrelas"]}
        presets._validar(p)

    def test_motor_marca_o_melhor_do_clipe(self):
        n = 40
        nit = [1000.0] * 16 + [5.0] * 6 + [700.0] * 18   # dois trechos; o primeiro é mais nítido
        sc = {"caminho": "/m/A.MP4", "fps": 24.0, "duracao": n * DT, "amostras_por_s": 1 / DT,
              "quadros": quadros_fake(n, nitidez=nit)}
        p = preset(campos={"marcador_nome": "{estrela}{id}", "marcador_nota": "{estrelas}", "relatorio": []})
        trechos, _ = trechos_do_clipe(sc, p)
        self.assertEqual(len(trechos), 2)
        melhores = [t for t in trechos if t["melhor_do_clipe"]]
        self.assertEqual(len(melhores), 1)
        self.assertEqual(melhores[0]["nota"], max(t["nota"] for t in trechos))
        self.assertTrue(melhores[0]["marcador"]["nome"].startswith("★"))
        outro = next(t for t in trechos if not t["melhor_do_clipe"])
        self.assertEqual(outro["marcador"]["nome"], outro["id"])
        self.assertEqual(len(outro["marcador"]["nota"]), 5)


if __name__ == "__main__":
    unittest.main()
