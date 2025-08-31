class ExpressionSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighting for QGIS expressions"""
    
    def __init__(self, document):
        super().__init__(document)
        self.highlighting_rules = []
        self.setup_rules()
    
    def setup_rules(self):
        """Configure highlighting rules"""
        # QGIS functions
        function_format = QTextCharFormat()
        function_format.setColor(QColor(0, 100, 200))
        function_format.setFontWeight(QFont.Bold)
        
        functions = [
            'area', 'perimeter', 'length', 'distance', 'centroid', 'bounds',
            'buffer', 'convex_hull', 'difference', 'intersection', 'union',
            'contains', 'crosses', 'disjoint', 'equals', 'intersects', 'overlaps',
            'touches', 'within', 'relate', 'transform', 'translate', 'rotate',
            'scale', 'geometry', 'geom_from_wkt', 'geom_to_wkt', 'x', 'y', 'z',
            'xmin', 'xmax', 'ymin', 'ymax', 'num_points', 'num_rings', 'num_geometries',
            'is_valid', 'make_point', 'make_line', 'make_polygon', 'nodes_to_points',
            'point_n', 'exterior_ring', 'interior_ring_n', 'geometry_n',
            'start_point', 'end_point', 'concat', 'substr', 'lower', 'upper',
            'title', 'trim', 'ltrim', 'rtrim', 'length', 'regexp_match', 'regexp_replace',
            'regexp_substr', 'strpos', 'left', 'right', 'rpad', 'lpad', 'format',
            'format_number', 'format_date', 'now', 'age', 'year', 'month', 'week',
            'day', 'hour', 'minute', 'second', 'epoch', 'datetime_from_epoch',
            'to_date', 'to_time', 'to_datetime', 'to_interval', 'day_of_week',
            'abs', 'acos', 'asin', 'atan', 'atan2', 'ceil', 'cos', 'degrees',
            'exp', 'floor', 'ln', 'log', 'log10', 'max', 'min', 'pi', 'power',
            'radians', 'rand', 'randf', 'round', 'sin', 'sqrt', 'tan', 'clamp',
            'coalesce', 'if', 'try', 'attribute', 'get_feature', 'get_feature_by_id'
        ]
        
        for func in functions:
            pattern = f'\\b{func}\\b'
            self.highlighting_rules.append((pattern, function_format))
        
        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setColor(QColor(150, 0, 150))
        keyword_format.setFontWeight(QFont.Bold)
        
        keywords = ['AND', 'OR', 'NOT', 'IN', 'IS', 'NULL', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END']
        for keyword in keywords:
            pattern = f'\\b{keyword}\\b'
            self.highlighting_rules.append((pattern, keyword_format))
        
        # Strings
        string_format = QTextCharFormat()
        string_format.setColor(QColor(0, 150, 0))
        self.highlighting_rules.append(("'[^']*'", string_format))
        self.highlighting_rules.append(('"[^"]*"', string_format))
        
        # Numbers
        number_format = QTextCharFormat()
        number_format.setColor(QColor(200, 100, 0))
        self.highlighting_rules.append(("\\b\\d+\\.?\\d*\\b", number_format))
        
        # Fields (double quoted)
        field_format = QTextCharFormat()
        field_format.setColor(QColor(0, 0, 200))
        field_format.setFontItalic(True)
        self.highlighting_rules.append(('"[^"]*"', field_format))
        
        # Comments
        comment_format = QTextCharFormat()
        comment_format.setColor(QColor(128, 128, 128))
        comment_format.setFontItalic(True)
        self.highlighting_rules.append(("--[^\n]*", comment_format))
    
    def highlightBlock(self, text):
        """Apply syntax highlighting to text block"""
        for pattern, format_obj in self.highlighting_rules:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start, end = match.span()
                self.setFormat(start, end - start, format_obj)

