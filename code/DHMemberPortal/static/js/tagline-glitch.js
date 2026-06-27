/* ===================================================================
   Tagline Glitch — cycles "Hackerspace" ↔ "Makerspace" with random
   animation effects at random intervals (20-60s).
   Feature idea by @jcmertz
   =================================================================== */
(function () {
    var words = ["Hackerspace", "Makerspace\u00A0"];
    var scrambleChars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%&*";
    var binaryChars = "01001011001010110100101101";
    var staticChars = "\u2591\u2592\u2593\u2588\u2580\u2584\u258C\u2590";
    var prideColors = ["#E40303", "#FF8C00", "#FFED00", "#008026", "#004DFF", "#750787"];
    var transColors = ["#55CDFC", "#F7A8B8", "#B0B0B0", "#F7A8B8", "#55CDFC"];

    var currentWord = words[Math.floor(Math.random() * words.length)];
    var animating = false;

    function otherWord() {
        return currentWord === words[0] ? words[1] : words[0];
    }

    /* Build a single <span> node with optional color and a single char.
       XSS-safe: textContent only, no markup strings. */
    function colorSpan(ch, color) {
        var span = document.createElement("span");
        if (color) span.style.color = color;
        span.textContent = ch;
        return span;
    }

    function randomInterval() {
        return 20000 + Math.random() * 40000; // 20-60s
    }

    /* Get all tagline word elements */
    function getEls() {
        return ["sub-tagline", "sub-tagline-mobile"].map(function (id) {
            return document.getElementById(id);
        }).filter(Boolean);
    }

    /* Initialize tagline text on page load */
    getEls().forEach(function (el) {
        el.textContent = currentWord;
    });

    /* ========== Effect 1: Character Scramble ========== */
    function scramble(el, target, callback) {
        var len = Math.max(el.textContent.length, target.length);
        var iterations = 0;
        var maxIterations = 12;
        var settled = new Array(len).fill(false);

        var interval = setInterval(function () {
            iterations++;
            var result = "";
            for (var i = 0; i < len; i++) {
                if (settled[i]) {
                    result += i < target.length ? target[i] : "";
                } else if (iterations > maxIterations - (len - i)) {
                    settled[i] = true;
                    result += i < target.length ? target[i] : "";
                } else {
                    result += scrambleChars[Math.floor(Math.random() * scrambleChars.length)];
                }
            }
            el.textContent = result;
            if (iterations >= maxIterations) {
                clearInterval(interval);
                el.textContent = target;
                if (callback) callback();
            }
        }, 50);
    }

    /* ========== Effect 2: Typewriter Delete & Retype ========== */
    function typewriter(el, target, callback) {
        var current = el.textContent;
        // Insert cursor
        var cursor = document.createElement("span");
        cursor.className = "tagline-cursor";
        el.parentNode.insertBefore(cursor, el.nextSibling);
        var i = current.length;

        var delInterval = setInterval(function () {
            i--;
            el.textContent = current.substring(0, i);
            if (i <= 0) {
                clearInterval(delInterval);
                var j = 0;
                var typeInterval = setInterval(function () {
                    j++;
                    el.textContent = target.substring(0, j);
                    if (j >= target.length) {
                        clearInterval(typeInterval);
                        if (cursor.parentNode) cursor.parentNode.removeChild(cursor);
                        if (callback) callback();
                    }
                }, 60);
            }
        }, 40);
    }

    /* ========== Effect 3: Binary Flash ========== */
    function binaryFlash(el, target, callback) {
        var flashes = 0;
        var maxFlashes = 6;
        var interval = setInterval(function () {
            flashes++;
            if (flashes <= maxFlashes) {
                var noise = "";
                for (var i = 0; i < target.length; i++) {
                    noise += binaryChars[Math.floor(Math.random() * binaryChars.length)];
                }
                el.textContent = noise;
                el.style.color = flashes % 2 === 0 ? "" : "#16a34a";
            } else {
                clearInterval(interval);
                el.textContent = target;
                el.style.color = "";
                if (callback) callback();
            }
        }, 60);
    }

    /* ========== Effect 4: CSS Glitch RGB Split ========== */
    function rgbGlitch(el, target, callback) {
        el.classList.add("glitch-rgb", "active");
        el.setAttribute("data-text", el.textContent);

        setTimeout(function () {
            el.textContent = target;
            el.setAttribute("data-text", target);
        }, 200);

        setTimeout(function () {
            el.classList.remove("glitch-rgb", "active");
            el.removeAttribute("data-text");
            if (callback) callback();
        }, 400);
    }

    /* ========== Effect 5: Split-Flap Flip ========== */
    function splitFlap(el, target, callback) {
        var current = el.textContent;
        var maxLen = Math.max(current.length, target.length);

        el.textContent = "";
        for (var i = 0; i < maxLen; i++) {
            var span = colorSpan(i < current.length ? current[i] : "", null);
            span.className = "flip-char";
            el.appendChild(span);
        }
        var chars = el.querySelectorAll(".flip-char");

        chars.forEach(function (charEl, idx) {
            setTimeout(function () {
                charEl.classList.add("flipping");
                setTimeout(function () {
                    charEl.textContent = idx < target.length ? target[idx] : "";
                }, 150);
                charEl.addEventListener("animationend", function () {
                    charEl.classList.remove("flipping");
                }, { once: true });
            }, idx * 40);
        });

        setTimeout(function () {
            el.textContent = target;
            if (callback) callback();
        }, maxLen * 40 + 350);
    }

    /* ========== Effect 6: Fade Through Static ========== */
    function staticDissolve(el, target, callback) {
        var current = el.textContent;
        var len = Math.max(current.length, target.length);
        var phase = 0;
        var steps = 0;

        var interval = setInterval(function () {
            steps++;
            var result = "";
            for (var i = 0; i < len; i++) {
                if (phase === 0) {
                    if (Math.random() < steps / 6) {
                        result += staticChars[Math.floor(Math.random() * staticChars.length)];
                    } else {
                        result += i < current.length ? current[i] : "";
                    }
                } else if (phase === 1) {
                    result += staticChars[Math.floor(Math.random() * staticChars.length)];
                } else {
                    if (Math.random() < (steps - 10) / 5) {
                        result += i < target.length ? target[i] : "";
                    } else {
                        result += staticChars[Math.floor(Math.random() * staticChars.length)];
                    }
                }
            }
            el.textContent = result;

            if (phase === 0 && steps >= 6) phase = 1;
            else if (phase === 1 && steps >= 10) phase = 2;
            else if (phase === 2 && steps >= 16) {
                clearInterval(interval);
                el.textContent = target;
                if (callback) callback();
            }
        }, 60);
    }

    /* ========== Effect 7: Pride Rainbow Wave ========== */
    function prideScramble(el, target, colors, callback) {
        var len = Math.max(el.textContent.length, target.length);
        var iterations = 0;
        var maxIterations = 16;
        var settled = new Array(len).fill(false);
        var colorOffset = 0;

        var interval = setInterval(function () {
            iterations++;
            colorOffset++;
            el.textContent = "";
            for (var i = 0; i < len; i++) {
                var color = colors[(i + colorOffset) % colors.length];
                if (settled[i]) {
                    var ch = i < target.length ? target[i] : " ";
                    el.appendChild(colorSpan(ch, "var(--secondary-color)"));
                } else if (iterations > maxIterations - (len - i)) {
                    settled[i] = true;
                    var ch = i < target.length ? target[i] : " ";
                    el.appendChild(colorSpan(ch, color));
                } else {
                    var ch = scrambleChars[Math.floor(Math.random() * scrambleChars.length)];
                    el.appendChild(colorSpan(ch, color));
                }
            }
            if (iterations >= maxIterations) {
                clearInterval(interval);
                el.textContent = "";
                for (var i = 0; i < target.length; i++) {
                    el.appendChild(colorSpan(target[i], colors[i % colors.length]));
                }
                setTimeout(function () {
                    el.textContent = target;
                    if (callback) callback();
                }, 600);
            }
        }, 50);
    }

    /* ========== Effect dispatcher ========== */
    var effects = [
        function (el, target, cb) { scramble(el, target, cb); },
        function (el, target, cb) { typewriter(el, target, cb); },
        function (el, target, cb) { binaryFlash(el, target, cb); },
        function (el, target, cb) { rgbGlitch(el, target, cb); },
        function (el, target, cb) { splitFlap(el, target, cb); },
        function (el, target, cb) { staticDissolve(el, target, cb); },
        function (el, target, cb) { prideScramble(el, target, prideColors, cb); },
        function (el, target, cb) { prideScramble(el, target, transColors, cb); }
    ];

    /* ========== Scheduler ========== */
    function scheduleNext() {
        setTimeout(function () {
            if (animating) return scheduleNext();
            animating = true;
            var target = otherWord();
            var els = getEls();
            var effectIndex = Math.floor(Math.random() * effects.length);
            var done = 0;

            els.forEach(function (el) {
                effects[effectIndex](el, target, function () {
                    done++;
                    if (done >= els.length) {
                        currentWord = target;
                        animating = false;
                        scheduleNext();
                    }
                });
            });

            // Safety: if no elements found, keep going
            if (els.length === 0) {
                currentWord = target;
                animating = false;
                scheduleNext();
            }
        }, randomInterval());
    }

    scheduleNext();
})();
