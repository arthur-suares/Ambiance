import * as THREE from "three";

const wallpaperToggle = document.querySelector(".wallpaper-toggle");
let savedWallpaper = null;
try {
    savedWallpaper = window.localStorage.getItem("ambiance-wallpaper");
} catch (error) {
    console.warn("Não foi possível ler a preferência de papel de parede.", error);
}
let flatWallpaper = savedWallpaper === "flat";
let renderWallpaper = () => {};
let updateWallpaperScene = () => {};

const setWallpaper = (flat) => {
    flatWallpaper = flat;
    document.body.classList.toggle("flat-wallpaper", flat);
    if (wallpaperToggle) {
        wallpaperToggle.setAttribute("aria-pressed", String(flat));
        wallpaperToggle.setAttribute(
            "aria-label",
            flat ? "Trocar para Terra Redonda" : "Trocar para Terra Plana",
        );
    }
    updateWallpaperScene(flat);
    try {
        window.localStorage.setItem("ambiance-wallpaper", flat ? "flat" : "round");
    } catch (error) {
        console.warn("Não foi possível salvar a preferência de papel de parede.", error);
    }
    renderWallpaper();
};

setWallpaper(flatWallpaper);
wallpaperToggle?.addEventListener("click", () => setWallpaper(!flatWallpaper));

const host = document.querySelector("#globe-scene");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const explorePlatform = document.querySelector("#explore-platform");

if (explorePlatform && !reducedMotion) {
    explorePlatform.addEventListener("click", (event) => {
        if (
            event.defaultPrevented ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
        ) {
            return;
        }

        event.preventDefault();
        document.body.classList.add("leaving-landing");
        window.setTimeout(() => window.location.assign(explorePlatform.href), 360);
    });
}

if (host) {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
    camera.position.set(0, 0, 7.5);

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    const globe = new THREE.Group();
    globe.position.set(0, -1.1, 0);
    scene.add(globe);
    globe.visible = !flatWallpaper;

    const flatWorld = new THREE.Group();
    flatWorld.position.set(0, -1.1, 0);
    flatWorld.rotation.x = 0;
    flatWorld.visible = flatWallpaper;
    scene.add(flatWorld);
    updateWallpaperScene = (flat) => {
        globe.visible = !flat;
        flatWorld.visible = flat;
        if (flat) {
            camera.position.set(0, 2.4, 6.8);
            camera.lookAt(0, 0, 0);
        } else {
            camera.position.set(0, 0, 7.5);
            camera.lookAt(0, 0, 0);
        }
    };
    updateWallpaperScene(flatWallpaper);

    const createPolarMap = () => {
        const canvas = document.createElement("canvas");
        canvas.width = 1536;
        canvas.height = 1536;
        const context = canvas.getContext("2d");
        const center = canvas.width / 2;
        const radius = canvas.width / 2;

        const ocean = context.createRadialGradient(center, center, 30, center, center, radius);
        ocean.addColorStop(0, "#355b73");
        ocean.addColorStop(0.52, "#2e4a63");
        ocean.addColorStop(0.9, "#24445e");
        ocean.addColorStop(1, "#142d42");
        context.fillStyle = ocean;
        context.fillRect(0, 0, canvas.width, canvas.height);

        context.save();
        context.beginPath();
        context.arc(center, center, radius - 4, 0, Math.PI * 2);
        context.clip();

        const landShapes = [
            [[.18,.23],[.25,.16],[.34,.18],[.38,.26],[.35,.33],[.29,.35],[.27,.42],[.20,.39],[.16,.31]],
            [[.40,.12],[.45,.08],[.48,.13],[.46,.20],[.41,.19]],
            [[.54,.12],[.62,.10],[.67,.17],[.63,.24],[.56,.23],[.52,.18]],
            [[.72,.22],[.81,.20],[.88,.27],[.85,.34],[.78,.37],[.73,.32]],
            [[.14,.49],[.22,.44],[.29,.48],[.31,.57],[.25,.64],[.18,.61]],
            [[.39,.38],[.47,.34],[.53,.39],[.55,.47],[.50,.53],[.42,.51],[.37,.45]],
            [[.63,.42],[.73,.40],[.79,.46],[.77,.55],[.70,.59],[.64,.53]],
            [[.34,.69],[.43,.65],[.49,.70],[.47,.78],[.40,.82],[.35,.77]],
            [[.55,.69],[.62,.65],[.68,.69],[.70,.76],[.64,.81],[.57,.78]],
            [[.80,.57],[.87,.55],[.91,.61],[.88,.68],[.82,.67]],
        ];
        context.fillStyle = "#6c7878";
        context.strokeStyle = "rgba(197, 219, 218, .24)";
        context.lineWidth = 5;
        landShapes.forEach((shape, shapeIndex) => {
            const points = shape.map(([x, y]) => [
                center + (x - 0.5) * canvas.width,
                center + (y - 0.5) * canvas.height,
            ]);
            context.beginPath();
            points.forEach(([x, y], index) => {
                if (index === 0) context.moveTo(x, y);
                else {
                    const [previousX, previousY] = points[index - 1];
                    context.quadraticCurveTo(previousX, previousY, (previousX + x) / 2, (previousY + y) / 2);
                }
            });
            context.closePath();
            context.fill();
            context.stroke();
            context.globalAlpha = 0.13;
            context.fillStyle = shapeIndex % 2 ? "#a3b2a1" : "#b7c5ad";
            context.fill();
            context.globalAlpha = 1;
            context.fillStyle = "#6c7878";
        });

        let seed = 193;
        const random = () => {
            seed = (seed * 16807) % 2147483647;
            return (seed - 1) / 2147483646;
        };
        for (let index = 0; index < 14000; index++) {
            const angle = random() * Math.PI * 2;
            const distance = Math.sqrt(random()) * (radius - 8);
            const x = center + Math.cos(angle) * distance;
            const y = center + Math.sin(angle) * distance;
            context.fillStyle = random() > 0.5
                ? "rgba(177, 207, 213, 0.035)"
                : "rgba(5, 24, 35, 0.055)";
            context.fillRect(x, y, 1 + random() * 2, 1 + random() * 2);
        }

        const rings = [0.2, 0.43, 0.69, 0.86];
        context.strokeStyle = "rgba(177, 212, 219, .14)";
        context.lineWidth = 2;
        rings.forEach((ring) => {
            context.beginPath();
            context.arc(center, center, radius * ring, 0, Math.PI * 2);
            context.stroke();
        });
        context.strokeStyle = "rgba(177, 212, 219, .11)";
        context.lineWidth = 1;
        for (let angle = 0; angle < Math.PI * 2; angle += Math.PI / 12) {
            context.beginPath();
            context.moveTo(center, center);
            context.lineTo(center + Math.cos(angle) * radius, center + Math.sin(angle) * radius);
            context.stroke();
        }

        const poleGlow = context.createRadialGradient(center, center, 0, center, center, radius * 0.09);
        poleGlow.addColorStop(0, "rgba(242, 250, 246, .96)");
        poleGlow.addColorStop(0.3, "rgba(198, 225, 228, .78)");
        poleGlow.addColorStop(1, "rgba(198, 225, 228, 0)");
        context.fillStyle = poleGlow;
        context.fillRect(center - radius * 0.1, center - radius * 0.1, radius * 0.2, radius * 0.2);
        context.restore();

        const texture = new THREE.CanvasTexture(canvas);
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.anisotropy = Math.min(renderer.capabilities.getMaxAnisotropy(), 4);
        return texture;
    };

    const createCloudMap = () => {
        const canvas = document.createElement("canvas");
        canvas.width = 1024;
        canvas.height = 1024;
        const context = canvas.getContext("2d");
        let seed = 79;
        const random = () => {
            seed = (seed * 16807) % 2147483647;
            return (seed - 1) / 2147483646;
        };
        for (let index = 0; index < 900; index++) {
            const x = random() * canvas.width;
            const y = random() * canvas.height;
            const width = 12 + random() * 90;
            const height = 4 + random() * 30;
            context.fillStyle = `rgba(218, 234, 239, ${0.025 + random() * 0.08})`;
            context.beginPath();
            context.ellipse(x, y, width, height, random() * Math.PI, 0, Math.PI * 2);
            context.fill();
        }
        const texture = new THREE.CanvasTexture(canvas);
        texture.colorSpace = THREE.SRGBColorSpace;
        return texture;
    };

    const surfaceMaterial = new THREE.MeshStandardMaterial({
        map: createPolarMap(),
        roughness: 0.94,
        metalness: 0.02,
    });
    const surfaceLighting = {
        sun: new THREE.Vector2(),
        moon: new THREE.Vector2(),
    };
    surfaceMaterial.onBeforeCompile = (shader) => {
        shader.uniforms.uSunPosition = { value: surfaceLighting.sun };
        shader.uniforms.uMoonPosition = { value: surfaceLighting.moon };
        shader.vertexShader = shader.vertexShader.replace(
            "#include <common>",
            "#include <common>\nvarying vec2 vFlatPosition;",
        );
        shader.vertexShader = shader.vertexShader.replace(
            "#include <begin_vertex>",
            "#include <begin_vertex>\nvFlatPosition = position.xz;",
        );
        shader.fragmentShader = shader.fragmentShader.replace(
            "#include <common>",
            "#include <common>\nuniform vec2 uSunPosition;\nuniform vec2 uMoonPosition;\nvarying vec2 vFlatPosition;",
        );
        shader.fragmentShader = shader.fragmentShader.replace(
            "#include <map_fragment>",
            `#include <map_fragment>
            float sunDistance = distance(vFlatPosition, uSunPosition);
            float moonDistance = distance(vFlatPosition, uMoonPosition);
            float sunGlow = exp(-sunDistance * sunDistance / 1.8);
            float moonShade = exp(-moonDistance * moonDistance / 1.0);
            float dayMix = smoothstep(0.05, 0.72, sunGlow);
            float nightMix = smoothstep(0.12, 0.85, moonShade);
            vec3 nightSurface = diffuseColor.rgb * 0.2;
            vec3 daySurface = diffuseColor.rgb * 1.75 + vec3(0.06, 0.08, 0.1);
            diffuseColor.rgb = mix(nightSurface, daySurface, dayMix);
            diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * 0.07, nightMix);`,
        );
    };
    surfaceMaterial.customProgramCacheKey = () => "flat-earth-sun-moon-lighting-v1";
    const flatSurface = new THREE.Group();
    flatWorld.add(flatSurface);
    const applyPolarEarthTexture = (image) => {
        try {
            const sourceCanvas = document.createElement("canvas");
            sourceCanvas.width = image.naturalWidth || image.width;
            sourceCanvas.height = image.naturalHeight || image.height;
            const sourceContext = sourceCanvas.getContext("2d", { willReadFrequently: true });
            sourceContext.drawImage(image, 0, 0, sourceCanvas.width, sourceCanvas.height);
            const source = sourceContext.getImageData(0, 0, sourceCanvas.width, sourceCanvas.height);

            const canvas = document.createElement("canvas");
            canvas.width = 1024;
            canvas.height = 1024;
            const context = canvas.getContext("2d");
            const output = context.createImageData(canvas.width, canvas.height);
            const center = canvas.width / 2;
            const radius = center - 2;
            const sourceWidth = sourceCanvas.width;
            const sourceHeight = sourceCanvas.height;
            const palette = {
                oceanDeep: [36, 68, 94],
                ocean: [46, 74, 99],
                land: [108, 120, 120],
                ice: [131, 154, 171],
            };
            const smooth = (min, max, value) => {
                const amount = Math.max(0, Math.min(1, (value - min) / (max - min)));
                return amount * amount * (3 - 2 * amount);
            };

            for (let y = 0; y < canvas.height; y++) {
                const dy = (y - center) / radius;
                for (let x = 0; x < canvas.width; x++) {
                    const dx = (x - center) / radius;
                    const radial = Math.sqrt(dx * dx + dy * dy);
                    if (radial > 1) continue;

                    const angle = (Math.atan2(dy, dx) + Math.PI * 2) % (Math.PI * 2);
                    const sourceX = Math.floor(angle / (Math.PI * 2) * sourceWidth) % sourceWidth;
                    const sourceY = Math.min(sourceHeight - 1, Math.floor(radial * (sourceHeight - 1)));
                    const sourceIndex = (sourceY * sourceWidth + sourceX) * 4;
                    const red = source.data[sourceIndex];
                    const green = source.data[sourceIndex + 1];
                    const blue = source.data[sourceIndex + 2];
                    const luminance = (red * 0.299 + green * 0.587 + blue * 0.114) / 255;
                    const oceanMask = smooth(0.008, 0.032, (blue - green) / 255);
                    const landIce = smooth(0.26, 0.65, luminance) * 0.45;
                    const detail = 0.58 + smooth(0.02, 0.32, luminance) * 0.92;
                    const oceanBlend = 0.62 + smooth(0.03, 0.26, luminance) * 0.16;
                    const landRed = (palette.land[0] + (palette.ice[0] - palette.land[0]) * landIce) * detail;
                    const landGreen = (palette.land[1] + (palette.ice[1] - palette.land[1]) * landIce) * detail;
                    const landBlue = (palette.land[2] + (palette.ice[2] - palette.land[2]) * landIce) * detail;
                    const oceanRed = (palette.oceanDeep[0] + (palette.ocean[0] - palette.oceanDeep[0]) * oceanBlend) * detail;
                    const oceanGreen = (palette.oceanDeep[1] + (palette.ocean[1] - palette.oceanDeep[1]) * oceanBlend) * detail;
                    const oceanBlue = (palette.oceanDeep[2] + (palette.ocean[2] - palette.oceanDeep[2]) * oceanBlend) * detail;
                    const outputIndex = (y * canvas.width + x) * 4;
                    output.data[outputIndex] = landRed + (oceanRed - landRed) * oceanMask;
                    output.data[outputIndex + 1] = landGreen + (oceanGreen - landGreen) * oceanMask;
                    output.data[outputIndex + 2] = landBlue + (oceanBlue - landBlue) * oceanMask;
                    output.data[outputIndex + 3] = 255;
                }
            }
            context.putImageData(output, 0, 0);
            const texture = new THREE.CanvasTexture(canvas);
            texture.colorSpace = THREE.SRGBColorSpace;
            texture.anisotropy = Math.min(renderer.capabilities.getMaxAnisotropy(), 4);
            surfaceMaterial.map.dispose();
            surfaceMaterial.map = texture;
            surfaceMaterial.needsUpdate = true;
            renderWallpaper();
        } catch (error) {
            console.warn("Não foi possível projetar a textura detalhada na Terra Plana.", error);
        }
    };
    const iceMaterial = new THREE.MeshStandardMaterial({
        color: "#c5dce1",
        emissive: "#43647a",
        emissiveIntensity: 0.3,
        roughness: 0.46,
        metalness: 0.08,
    });
    const disk = new THREE.Mesh(
        new THREE.CylinderGeometry(2.85, 2.85, 0.16, 128, 1),
        [new THREE.MeshStandardMaterial({ color: "#20394b", roughness: 0.8 }), surfaceMaterial, new THREE.MeshStandardMaterial({ color: "#142b3a", roughness: 0.85 })],
    );
    disk.receiveShadow = true;
    flatSurface.add(disk);

    const iceWall = new THREE.Mesh(new THREE.TorusGeometry(2.82, 0.13, 16, 144), iceMaterial);
    iceWall.rotation.x = Math.PI / 2;
    iceWall.position.y = -0.015;
    iceWall.castShadow = true;
    iceWall.receiveShadow = true;
    flatSurface.add(iceWall);

    const iceCliff = new THREE.Mesh(
        new THREE.CylinderGeometry(2.87, 2.85, 0.34, 144, 1, true),
        new THREE.MeshStandardMaterial({
            color: "#839AAB",
            emissive: "#43647a",
            emissiveIntensity: 0.32,
            roughness: 0.48,
            metalness: 0.08,
            side: THREE.DoubleSide,
        }),
    );
    iceCliff.position.y = 0.12;
    iceCliff.castShadow = true;
    iceCliff.receiveShadow = true;
    flatSurface.add(iceCliff);

    const iceRim = new THREE.Mesh(
        new THREE.TorusGeometry(2.86, 0.045, 10, 144),
        new THREE.MeshStandardMaterial({
            color: "#e1edf0",
            emissive: "#839AAB",
            emissiveIntensity: 0.24,
            roughness: 0.38,
            metalness: 0.1,
        }),
    );
    iceRim.rotation.x = Math.PI / 2;
    iceRim.position.y = 0.295;
    iceRim.castShadow = true;
    flatSurface.add(iceRim);

    const cloudLayer = new THREE.Mesh(
        new THREE.CircleGeometry(2.72, 96),
        new THREE.MeshBasicMaterial({
            map: createCloudMap(),
            transparent: true,
            opacity: 0.5,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
        }),
    );
    cloudLayer.rotation.x = -Math.PI / 2;
    cloudLayer.position.y = 0.088;
    flatSurface.add(cloudLayer);

    const domeGeometry = new THREE.SphereGeometry(3.1, 48, 28, 0, Math.PI * 2, 0, Math.PI / 2);
    const dome = new THREE.Mesh(
        domeGeometry,
        new THREE.MeshBasicMaterial({
            color: "#839AAB",
            transparent: true,
            opacity: 0.085,
            side: THREE.BackSide,
            depthWrite: false,
        }),
    );
    dome.position.y = 0.08;
    dome.scale.y = 0.68;
    flatWorld.add(dome);
    const domeLines = new THREE.LineSegments(
        new THREE.WireframeGeometry(domeGeometry),
        new THREE.LineBasicMaterial({ color: "#839AAB", transparent: true, opacity: 0.075 }),
    );
    domeLines.position.copy(dome.position);
    domeLines.scale.y = 0.68;
    flatWorld.add(domeLines);

    const starPositions = [];
    let starSeed = 109;
    const starRandom = () => {
        starSeed = (starSeed * 16807) % 2147483647;
        return (starSeed - 1) / 2147483646;
    };
    for (let index = 0; index < 380; index++) {
        const angle = starRandom() * Math.PI * 2;
        const height = 0.08 + starRandom() * 0.9;
        const radius = 3.02 + starRandom() * 0.08;
        const horizontal = Math.sqrt(1 - height * height);
        starPositions.push(
            Math.cos(angle) * horizontal * radius,
            height * radius * 0.68 + 0.08,
            Math.sin(angle) * horizontal * radius,
        );
    }
    const starGeometry = new THREE.BufferGeometry();
    starGeometry.setAttribute("position", new THREE.Float32BufferAttribute(starPositions, 3));
    const domeStars = new THREE.Points(
        starGeometry,
        new THREE.PointsMaterial({ color: "#d8eaff", size: 0.035, transparent: true, opacity: 0.8, sizeAttenuation: true }),
    );
    flatWorld.add(domeStars);

    const makeGlowTexture = () => {
        const canvas = document.createElement("canvas");
        canvas.width = 128;
        canvas.height = 128;
        const context = canvas.getContext("2d");
        const glow = context.createRadialGradient(64, 64, 2, 64, 64, 64);
        glow.addColorStop(0, "rgba(255,255,255,0.95)");
        glow.addColorStop(0.12, "rgba(255,231,173,0.75)");
        glow.addColorStop(0.38, "rgba(255,177,91,0.24)");
        glow.addColorStop(1, "rgba(255,177,91,0)");
        context.fillStyle = glow;
        context.fillRect(0, 0, 128, 128);
        return new THREE.CanvasTexture(canvas);
    };
    const glowTexture = makeGlowTexture();
    const sun = new THREE.Group();
    const sunMesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.14, 24, 16),
        new THREE.MeshBasicMaterial({ color: "#ffd48a" }),
    );
    const sunGlow = new THREE.Sprite(new THREE.SpriteMaterial({
        map: glowTexture,
        color: "#ffc46b",
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
    }));
    sunGlow.scale.set(1.1, 1.1, 1);
    sun.add(sunGlow, sunMesh);
    flatWorld.add(sun);

    const moon = new THREE.Group();
    const moonMesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.19, 32, 24),
        new THREE.MeshStandardMaterial({
            color: "#c9d3d7",
            emissive: "#526879",
            emissiveIntensity: 0.22,
            roughness: 0.82,
        }),
    );
    moonMesh.castShadow = true;
    moon.add(moonMesh);
    const moonGlow = new THREE.Sprite(new THREE.SpriteMaterial({
        map: glowTexture,
        color: "#b9d1df",
        transparent: true,
        opacity: 0.28,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
    }));
    moonGlow.scale.set(0.75, 0.75, 1);
    moon.add(moonGlow);
    flatWorld.add(moon);

    const sunLight = new THREE.DirectionalLight("#fff0cf", 2.2);
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.set(512, 512);
    sunLight.shadow.camera.left = -3.5;
    sunLight.shadow.camera.right = 3.5;
    sunLight.shadow.camera.top = 3.5;
    sunLight.shadow.camera.bottom = -3.5;
    flatWorld.add(sunLight);
    const flatAmbient = new THREE.HemisphereLight("#bcd4e2", "#182b3c", 0.68);
    flatWorld.add(flatAmbient);

    const orbitLineMaterial = new THREE.MeshBasicMaterial({
        color: "#839AAB",
        transparent: true,
        opacity: 0.16,
        depthWrite: false,
    });
    [1.65, 2.2].forEach((radius) => {
        const orbit = new THREE.Mesh(new THREE.TorusGeometry(radius, 0.006, 6, 128), orbitLineMaterial);
        orbit.rotation.x = Math.PI / 2;
        orbit.position.y = 0.56;
        flatWorld.add(orbit);
    });

    const earthRadius = 2.85;
    const geometry = new THREE.SphereGeometry(earthRadius, 88, 64);
    const material = new THREE.MeshStandardMaterial({
        color: 0xffffff,
        emissive: 0x141e27,
        emissiveIntensity: 0.55,
        roughness: 1,
        metalness: 0,
    });
    const planetaryPalette = {
        oceanDeep: new THREE.Color("#24445E"),
        ocean: new THREE.Color("#2E4A63"),
        ice: new THREE.Color("#839AAB"),
        land: new THREE.Color("#6C7878"),
        night: new THREE.Color("#101918"),
    };
    material.onBeforeCompile = (shader) => {
        shader.uniforms.uOceanDeep = { value: planetaryPalette.oceanDeep };
        shader.uniforms.uOcean = { value: planetaryPalette.ocean };
        shader.uniforms.uIce = { value: planetaryPalette.ice };
        shader.uniforms.uLand = { value: planetaryPalette.land };
        shader.uniforms.uNight = { value: planetaryPalette.night };

        shader.vertexShader = shader.vertexShader.replace(
            "#include <common>",
            "#include <common>\nvarying vec3 vEarthWorldNormal;",
        );
        shader.vertexShader = shader.vertexShader.replace(
            "#include <defaultnormal_vertex>",
            "#include <defaultnormal_vertex>\nvEarthWorldNormal = normalize(mat3(modelMatrix) * objectNormal);",
        );
        shader.fragmentShader = shader.fragmentShader.replace(
            "#include <common>",
            `#include <common>
            uniform vec3 uOceanDeep;
            uniform vec3 uOcean;
            uniform vec3 uIce;
            uniform vec3 uLand;
            uniform vec3 uNight;
            varying vec3 vEarthWorldNormal;`,
        );
        shader.fragmentShader = shader.fragmentShader.replace(
            "#include <map_fragment>",
            `#include <map_fragment>
            vec3 sourceColor = diffuseColor.rgb;
            float sourceLuminance = dot(sourceColor, vec3(0.299, 0.587, 0.114));
            float oceanMask = smoothstep(0.008, 0.032, sourceColor.b - sourceColor.g);
            float landIce = smoothstep(0.26, 0.65, sourceLuminance) * (1.0 - oceanMask);
            float detail = mix(0.58, 1.5, smoothstep(0.02, 0.32, sourceLuminance));
            vec3 landColor = mix(uLand, uIce, landIce * 0.45);
            float oceanBlend = 0.62 + smoothstep(0.03, 0.26, sourceLuminance) * 0.16;
            vec3 oceanColor = mix(uOceanDeep, uOcean, oceanBlend);
            vec3 dayColor = mix(landColor, oceanColor, oceanMask) * detail;
            float dayLuminance = dot(dayColor, vec3(0.299, 0.587, 0.114));
            dayColor = mix(vec3(dayLuminance), dayColor, 1.32);
            float sunlight = max(dot(normalize(vEarthWorldNormal), normalize(vec3(-4.0, 3.0, 5.0))), 0.0);
            float dayMask = smoothstep(0.015, 0.42, sunlight);
            vec3 nightColor = mix(uNight, uOceanDeep, oceanMask * 0.28);
            diffuseColor.rgb = mix(nightColor, dayColor, dayMask);`,
        );
    };
    material.customProgramCacheKey = () => "earth-biome-palette-v4";
    const earth = new THREE.Mesh(geometry, material);
    earth.rotation.z = -0.13;
    globe.add(earth);

    const cityMaterial = new THREE.MeshBasicMaterial({
        map: new THREE.DataTexture(new Uint8Array([0, 0, 0, 0]), 1, 1, THREE.RGBAFormat),
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
    });
    cityMaterial.map.needsUpdate = true;
    cityMaterial.onBeforeCompile = (shader) => {
        shader.vertexShader = shader.vertexShader.replace(
            "#include <common>",
            "#include <common>\nvarying vec3 vEarthWorldNormal;",
        );
        shader.vertexShader = shader.vertexShader.replace(
            "#include <defaultnormal_vertex>",
            "#include <defaultnormal_vertex>\nvEarthWorldNormal = normalize(mat3(modelMatrix) * objectNormal);",
        );
        shader.fragmentShader = shader.fragmentShader.replace(
            "#include <common>",
            "#include <common>\nvarying vec3 vEarthWorldNormal;",
        );
        shader.fragmentShader = shader.fragmentShader.replace(
            "#include <map_fragment>",
            `#include <map_fragment>
            float citySignal = texture2D(map, vMapUv).r;
            float daylight = max(dot(normalize(vEarthWorldNormal), normalize(vec3(-4.0, 3.0, 5.0))), 0.0);
            float nightSide = 1.0 - smoothstep(0.0, 0.28, daylight);
            diffuseColor.rgb = vec3(1.0, 0.65, 0.32);
            diffuseColor.a *= smoothstep(0.025, 0.2, citySignal) * nightSide;`,
        );
    };
    cityMaterial.customProgramCacheKey = () => "earth-city-lights-night-side-v1";

    const cityLights = new THREE.Mesh(
        new THREE.SphereGeometry(earthRadius + 0.012, 88, 64),
        cityMaterial,
    );
    cityLights.rotation.z = earth.rotation.z;
    globe.add(cityLights);

    const cloudsMaterial = new THREE.MeshStandardMaterial({
        color: 0xf2f7fa,
        transparent: true,
        opacity: 0.38,
        depthWrite: false,
        roughness: 1,
    });
    const clouds = new THREE.Mesh(
        new THREE.SphereGeometry(earthRadius + 0.02, 88, 64),
        cloudsMaterial,
    );
    globe.add(clouds);

    scene.add(new THREE.HemisphereLight(0xd8ead8, 0x14231b, 1.8));
    scene.add(new THREE.AmbientLight(0xc4e4cd, 0.8));
    const sunlight = new THREE.DirectionalLight(0xeaf3df, 2.6);
    sunlight.position.set(-4, 3, 5);
    scene.add(sunlight);

    function makeFallbackMap() {
        const canvas = document.createElement("canvas");
        canvas.width = 2048;
        canvas.height = 1024;
        const context = canvas.getContext("2d");
        context.fillStyle = "#12392e";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.fillStyle = "#83ae79";
        const land = [
            [[.08,.25],[.13,.14],[.2,.12],[.24,.19],[.3,.22],[.28,.32],[.23,.37],[.21,.48],[.16,.52],[.12,.42]],
            [[.25,.51],[.3,.48],[.33,.58],[.32,.72],[.29,.87],[.26,.78],[.24,.64]],
            [[.43,.23],[.48,.2],[.5,.25],[.48,.31],[.44,.29]],
            [[.45,.32],[.53,.29],[.57,.35],[.55,.47],[.52,.59],[.49,.72],[.45,.62],[.43,.48]],
            [[.52,.23],[.61,.17],[.72,.18],[.79,.25],[.88,.27],[.91,.37],[.85,.43],[.78,.41],[.75,.48],[.68,.44],[.64,.36],[.57,.39]],
            [[.77,.57],[.84,.56],[.87,.63],[.84,.7],[.78,.68]],
            [[.12,.1],[.17,.06],[.21,.08],[.2,.14],[.15,.16]],
        ];
        for (const shape of land) {
            context.beginPath();
            context.moveTo(shape[0][0] * canvas.width, shape[0][1] * canvas.height);
            for (const [x, y] of shape.slice(1)) context.lineTo(x * canvas.width, y * canvas.height);
            context.closePath();
            context.fill();
        }
        const texture = new THREE.CanvasTexture(canvas);
        texture.colorSpace = THREE.SRGBColorSpace;
        material.map = texture;
        material.color.set(0xffffff);
        material.needsUpdate = true;
    }

    const textureLoader = new THREE.TextureLoader();
    textureLoader.load(
        "https://threejs.org/examples/textures/planets/earth_atmos_2048.jpg",
        (texture) => {
            texture.colorSpace = THREE.SRGBColorSpace;
            material.map = texture;
            material.needsUpdate = true;
            applyPolarEarthTexture(texture.image);
        },
        undefined,
        makeFallbackMap,
    );

    textureLoader.load(
        "https://threejs.org/examples/textures/planets/earth_lights_2048.png",
        (texture) => {
            texture.colorSpace = THREE.SRGBColorSpace;
            cityMaterial.map = texture;
            cityMaterial.needsUpdate = true;
        },
    );

    textureLoader.load(
        "https://threejs.org/examples/textures/planets/earth_clouds_1024.png",
        (texture) => {
            texture.colorSpace = THREE.SRGBColorSpace;
            cloudsMaterial.map = texture;
            cloudsMaterial.needsUpdate = true;
        },
        undefined,
        () => {
            const canvas = document.createElement("canvas");
            canvas.width = 1024;
            canvas.height = 512;
            const context = canvas.getContext("2d");
            let seed = 41;
            const random = () => {
                seed = (seed * 16807) % 2147483647;
                return (seed - 1) / 2147483646;
            };
            for (let index = 0; index < 180; index++) {
                const x = random() * canvas.width;
                const y = random() * canvas.height;
                const radius = 8 + random() * 36;
                context.fillStyle = `rgba(228, 239, 244, ${0.025 + random() * 0.06})`;
                context.beginPath();
                context.ellipse(x, y, radius * 1.8, radius * 0.6, random() * Math.PI, 0, Math.PI * 2);
                context.fill();
            }
            const fallbackClouds = new THREE.CanvasTexture(canvas);
            fallbackClouds.colorSpace = THREE.SRGBColorSpace;
            cloudsMaterial.map = fallbackClouds;
            cloudsMaterial.needsUpdate = true;
        },
    );

    const resize = () => {
        const width = host.clientWidth;
        const height = host.clientHeight;
        if (!width || !height) return;
        camera.aspect = width / height;
        camera.fov = camera.aspect < 0.8 ? 64 : 34;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height);
    };
    const resizeObserver = new ResizeObserver(resize);
    resize();
    resizeObserver.observe(host);
    window.addEventListener("resize", resize);
    window.addEventListener("beforeunload", () => resizeObserver.disconnect(), { once: true });

    const updateCelestials = (time) => {
        const solarAngle = time * 0.18;
        const lunarAngle = -time * 0.105 + 1.3;
        sun.position.set(
            Math.cos(solarAngle) * 1.65,
            0.62 + Math.sin(solarAngle * 0.5) * 0.14,
            Math.sin(solarAngle) * 1.65,
        );
        moon.position.set(
            Math.cos(lunarAngle) * 2.2,
            0.76 + Math.sin(lunarAngle * 0.5) * 0.12,
            Math.sin(lunarAngle) * 2.2,
        );
        sunLight.position.copy(sun.position);
        moon.rotation.y = time * 0.025;
        flatWorld.updateMatrixWorld(true);
        const sunOnSurface = flatSurface.worldToLocal(flatWorld.localToWorld(sun.position.clone()));
        const moonOnSurface = flatSurface.worldToLocal(flatWorld.localToWorld(moon.position.clone()));
        surfaceLighting.sun.set(sunOnSurface.x, sunOnSurface.z);
        surfaceLighting.moon.set(moonOnSurface.x, moonOnSurface.z);
    };
    const clock = new THREE.Clock();
    updateCelestials(0);
    renderWallpaper = () => renderer.render(scene, camera);

    const animate = () => {
        const time = clock.getElapsedTime();
        if (!reducedMotion) {
            if (flatWallpaper) {
                flatSurface.rotation.y += 0.00008;
                domeStars.rotation.y += 0.000015;
                updateCelestials(time);
                camera.position.set(Math.sin(time * 0.08) * 0.12, 2.4, 6.8);
                camera.lookAt(0, 0, 0);
            } else {
                globe.rotation.y += 0.00035;
                clouds.rotation.y += 0.00065;
            }
        }
        renderer.render(scene, camera);
        if (!reducedMotion) requestAnimationFrame(animate);
    };
    animate();
}