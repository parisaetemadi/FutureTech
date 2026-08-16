/* Squarified treemap layout (Bruls, Huizing & van Wijk, 2000).
   No dependencies. Returns rects in the same order as the input values. */
(function (global) {
  'use strict';

  function worstRatio(row, rowSum, shortSide) {
    var max = -Infinity, min = Infinity;
    for (var i = 0; i < row.length; i++) {
      if (row[i] > max) max = row[i];
      if (row[i] < min) min = row[i];
    }
    if (min <= 0 || rowSum <= 0) return Infinity;
    var s2 = rowSum * rowSum;
    var l2 = shortSide * shortSide;
    return Math.max((l2 * max) / s2, s2 / (l2 * min));
  }

  /**
   * @param {number[]} values  positive numbers, sorted descending by the caller
   * @param {{x:number,y:number,w:number,h:number}} rect
   * @returns {{x:number,y:number,w:number,h:number}[]}
   */
  function squarify(values, rect) {
    var out = [];
    var n = values.length;
    if (!n) return out;

    var total = 0;
    for (var i = 0; i < n; i++) total += Math.max(0, values[i]);
    if (total <= 0 || rect.w <= 0 || rect.h <= 0) {
      for (i = 0; i < n; i++) out.push({ x: rect.x, y: rect.y, w: 0, h: 0 });
      return out;
    }

    // Work in area units so row thickness maps directly onto pixels.
    var scale = (rect.w * rect.h) / total;
    var areas = new Array(n);
    for (i = 0; i < n; i++) areas[i] = Math.max(0, values[i]) * scale;

    var x = rect.x, y = rect.y, w = rect.w, h = rect.h;
    var idx = 0;

    while (idx < n) {
      var shortSide = Math.min(w, h);
      if (shortSide <= 0) {
        for (; idx < n; idx++) out.push({ x: x, y: y, w: 0, h: 0 });
        break;
      }

      var row = [areas[idx]];
      var rowSum = areas[idx];
      var j = idx + 1;

      while (j < n) {
        var candidate = row.concat([areas[j]]);
        if (worstRatio(candidate, rowSum + areas[j], shortSide) <= worstRatio(row, rowSum, shortSide)) {
          row = candidate;
          rowSum += areas[j];
          j++;
        } else {
          break;
        }
      }

      // Lay the row out along the short side.
      var thickness = rowSum / shortSide;
      var pos = 0;
      for (var k = 0; k < row.length; k++) {
        var len = thickness > 0 ? row[k] / thickness : 0;
        if (w >= h) {
          out.push({ x: x, y: y + pos, w: thickness, h: len });
        } else {
          out.push({ x: x + pos, y: y, w: len, h: thickness });
        }
        pos += len;
      }

      if (w >= h) { x += thickness; w -= thickness; }
      else { y += thickness; h -= thickness; }

      idx = j;
    }

    return out;
  }

  global.squarify = squarify;
})(this);
