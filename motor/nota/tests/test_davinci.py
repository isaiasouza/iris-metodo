from __future__ import annotations

import unittest

from davinci import cor_marcador, filtrar_trechos, planejar_marcadores, planejar_timeline

FPS = 24000 / 1001


def trecho(caminho="/m/A.MP4", inicio=0.0, fim=6.0, nota=0.9, flags=(), camera="parada", ident="A-1234_01"):
    return {"id": ident, "caminho": caminho, "inicio_s": inicio, "fim_s": fim, "fps": FPS, "nota": nota,
            "flags": list(flags), "camera": {"tipo": camera, "confianca": 1.0}, "motivo": "foco 1,00 · parada"}


class TestCor(unittest.TestCase):
    def test_faixas(self):
        self.assertEqual(cor_marcador(0.8), "Green")
        self.assertEqual(cor_marcador(0.79), "Yellow")
        self.assertEqual(cor_marcador(0.6), "Yellow")
        self.assertEqual(cor_marcador(0.59), "Blue")


class TestFiltrar(unittest.TestCase):
    def setUp(self):
        self.t = [trecho(nota=0.99), trecho(nota=0.9), trecho(nota=0.99, flags=["blur"]),
                  trecho(nota=0.99, camera="mao")]

    def test_sem_filtro_mantem_tudo(self):
        self.assertEqual(filtrar_trechos(self.t), self.t)

    def test_filtros_combinados(self):
        self.assertEqual(filtrar_trechos(self.t, nota_min=0.98, sem_flags=True, sem_mao=True), [self.t[0]])


class TestMarcadores(unittest.TestCase):
    def test_converte_segundos_em_quadros_do_clipe(self):
        novos, sem, existentes = planejar_marcadores([trecho(inicio=0.0, fim=6.0)], {"/m/A.MP4": (FPS, set())})
        self.assertEqual((sem, existentes), ([], 0))
        self.assertEqual(novos[0]["quadro"], 0)
        self.assertEqual(novos[0]["duracao"], 144)
        self.assertEqual(novos[0]["cor"], "Green")
        self.assertEqual(novos[0]["nome"], "A-1234_01")

    def test_nao_duplica_marcador_existente(self):
        novos, _, existentes = planejar_marcadores([trecho(inicio=1.0)], {"/m/A.MP4": (FPS, {24})})
        self.assertEqual((novos, existentes), ([], 1))

    def test_clipe_fora_do_media_pool(self):
        novos, sem, _ = planejar_marcadores([trecho(caminho="/m/X.MP4")], {"/m/A.MP4": (FPS, set())})
        self.assertEqual((novos, sem), ([], ["/m/X.MP4"]))

    def test_duracao_minima_de_um_quadro(self):
        novos, _, _ = planejar_marcadores([trecho(inicio=1.0, fim=1.0)], {"/m/A.MP4": (FPS, set())})
        self.assertEqual(novos[0]["duracao"], 1)


class TestTimeline(unittest.TestCase):
    def test_ordem_de_gravacao_e_quadro_final_exclusivo(self):
        t = [trecho(caminho="/m/B.MP4", inicio=0.0, fim=1.0), trecho(caminho="/m/A.MP4", inicio=10.0, fim=12.0),
             trecho(caminho="/m/A.MP4", inicio=2.0, fim=4.0)]
        itens, sem = planejar_timeline(t, {"/m/A.MP4": FPS, "/m/B.MP4": FPS})
        self.assertEqual(sem, [])
        self.assertEqual(itens, [("/m/A.MP4", 48, 96), ("/m/A.MP4", 240, 288), ("/m/B.MP4", 0, 24)])

    def test_ordem_por_nota_e_por_duracao(self):
        t = [trecho(caminho="/m/A.MP4", inicio=0.0, fim=2.0, nota=0.7),
             trecho(caminho="/m/A.MP4", inicio=5.0, fim=15.0, nota=0.8),
             trecho(caminho="/m/B.MP4", inicio=0.0, fim=4.0, nota=0.95)]
        fps = {"/m/A.MP4": FPS, "/m/B.MP4": FPS}
        por_nota, _ = planejar_timeline(t, fps, "nota")
        por_duracao, _ = planejar_timeline(t, fps, "duracao")
        self.assertEqual([i[0] for i in por_nota], ["/m/B.MP4", "/m/A.MP4", "/m/A.MP4"])
        self.assertEqual(por_nota[1][1], 120)
        self.assertEqual([(i[0], i[1]) for i in por_duracao], [("/m/A.MP4", 120), ("/m/B.MP4", 0), ("/m/A.MP4", 0)])

    def test_clipe_fora_do_media_pool(self):
        itens, sem = planejar_timeline([trecho(caminho="/m/X.MP4")], {})
        self.assertEqual((itens, sem), ([], ["/m/X.MP4"]))


if __name__ == "__main__":
    unittest.main()
