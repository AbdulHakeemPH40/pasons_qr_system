/* Specials page — rotating spotlight + sliding promo rows.
   Native scroll-snap does the physics; this only adds rotation,
   dots and arrow edge states. Reduced motion stops the autoplay. */
(function () {
  "use strict";

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

  /* ---- Rotating spotlight ---- */
  var track = document.querySelector("[data-spot-track]");
  if (track && track.children.length > 1) {
    var slides = Array.prototype.slice.call(track.children);
    var dots = Array.prototype.slice.call(
      track.parentNode.querySelectorAll("[data-spot-dot]")
    );
    var current = 0;
    var timer = null;
    var DELAY = 5200;

    var paint = function () {
      dots.forEach(function (dot, i) {
        if (i === current) {
          dot.setAttribute("aria-current", "true");
        } else {
          dot.removeAttribute("aria-current");
        }
      });
    };

    var goTo = function (i) {
      current = (i + slides.length) % slides.length;
      track.scrollTo({
        left: slides[current].offsetLeft,
        behavior: reduce.matches ? "auto" : "smooth",
      });
      paint();
    };

    /* Nearest slide by offsetLeft, not scrollLeft/width math: the track has
       a gap between slides, so width division drifts once gaps exist. */
    var read = function () {
      var pos = Math.abs(track.scrollLeft);
      var i = 0;
      var best = Infinity;
      slides.forEach(function (slide, k) {
        var d = Math.abs(slide.offsetLeft - pos);
        if (d < best) {
          best = d;
          i = k;
        }
      });
      if (i !== current) {
        current = i;
        paint();
      }
    };

    var stop = function () {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };

    var start = function () {
      stop();
      if (reduce.matches || slides.length < 2) return;
      timer = setInterval(function () {
        goTo(current + 1);
      }, DELAY);
    };

    dots.forEach(function (dot, i) {
      dot.addEventListener("click", function () {
        goTo(i);
        start();
      });
    });

    var pending = null;
    track.addEventListener(
      "scroll",
      function () {
        if (pending) return;
        pending = window.requestAnimationFrame(function () {
          pending = null;
          read();
        });
      },
      { passive: true }
    );

    track.addEventListener("pointerdown", stop);
    track.addEventListener("touchstart", stop, { passive: true });
    track.addEventListener("focusin", stop);
    track.addEventListener("pointerup", start);
    track.addEventListener("touchend", start);
    track.addEventListener("focusout", start);

    if (reduce.addEventListener) {
      reduce.addEventListener("change", start);
    }

    paint();
    start();
  }

  /* ---- Sliding rows: arrows + edge states ---- */
  Array.prototype.forEach.call(
    document.querySelectorAll(".spec-section"),
    function (section) {
      var row = section.querySelector("[data-row]");
      var prev = section.querySelector("[data-row-prev]");
      var next = section.querySelector("[data-row-next]");
      if (!row || !prev || !next) return;

      var step = function () {
        var card = row.querySelector(".promo-card");
        return card ? card.offsetWidth + 12 : row.clientWidth * 0.8;
      };

      var refresh = function () {
        var max = row.scrollWidth - row.clientWidth;
        var pos = Math.abs(row.scrollLeft);
        prev.disabled = pos <= 2;
        next.disabled = pos >= max - 2;
      };

      prev.addEventListener("click", function () {
        row.scrollBy({
          left: -step(),
          behavior: reduce.matches ? "auto" : "smooth",
        });
      });

      next.addEventListener("click", function () {
        row.scrollBy({
          left: step(),
          behavior: reduce.matches ? "auto" : "smooth",
        });
      });

      var pending = null;
      row.addEventListener(
        "scroll",
        function () {
          if (pending) return;
          pending = window.requestAnimationFrame(function () {
            pending = null;
            refresh();
          });
        },
        { passive: true }
      );

      window.addEventListener("resize", refresh);
      refresh();
    }
  );
})();
