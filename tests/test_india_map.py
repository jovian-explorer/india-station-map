import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from india_map import cached_file, load_stations, plot_map


class MapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def csv(self, text):
        path = self.root / 'stations.csv'
        path.write_text(text, encoding='utf-8')
        return path

    def test_station_validation(self):
        for row in ['A,nan,10', 'A,77,100', ',77,10', 'A,77,10\nA,78,11']:
            with self.subTest(row=row), self.assertRaises(ValueError):
                load_stations(self.csv('name,longitude,latitude\n' + row))
        station = load_stations(self.csv('name,longitude,latitude,label_dx\nA,77,10,0'))[0]
        self.assertEqual(station['dx'], 0)
        self.assertEqual(station['latitude'], 10)

    def test_offline_cache_does_not_connect(self):
        with patch('urllib.request.urlopen') as network:
            with self.assertRaises(FileNotFoundError):
                cached_file('https://example.com', self.root / 'missing', offline=True)
            cached = self.root / 'cached'
            cached.write_text('present')
            self.assertEqual(cached_file('https://example.com', cached, offline=True), cached)
            network.assert_not_called()

    def test_render_all_formats(self):
        boundary = self.root / 'boundary.geojson'
        boundary.write_text(json.dumps({'type':'FeatureCollection', 'features':[
            {'type':'Feature', 'properties':{}, 'geometry':{'type':'Polygon', 'coordinates':[
                [[72,7],[82,7],[82,25],[72,25],[72,7]]
            ]}}
        ]}))
        stations = load_stations(self.csv('name,longitude,latitude\nA,77,10'))
        for marker in ['antenna', 'circle']:
            fig, ax = plot_map(stations, boundary, marker=marker, reference_curves=True)
            self.assertIn('A', [text.get_text() for text in ax.texts])
            for extension in ['png', 'pdf', 'svg']:
                output = self.root / f'{marker}.{extension}'
                fig.savefig(output)
                self.assertGreater(output.stat().st_size, 100)
            plt.close(fig)


if __name__ == '__main__':
    unittest.main()
